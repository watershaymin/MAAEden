// Exercise the packaged GUI's focus consumer and task cancellation without opening
// a window, connecting to a controller, or generating a real jackpot notification.
using System.Runtime.Loader;

var package = Path.GetFullPath(args[0]);
var libs = Path.Combine(package, "libs");
AssemblyLoadContext.Default.Resolving += (_, name) =>
{
    var path = Path.Combine(libs, name.Name + ".dll");
    return File.Exists(path) ? AssemblyLoadContext.Default.LoadFromAssemblyPath(path) : null;
};
await Check.Run(package);

static class Check
{
    public static async Task Run(string package)
    {
        using var cancel = new CancellationTokenSource();
        var focus = new MFAAvalonia.Extensions.MaaFW.FocusHandler(new MFAAvalonia.Helper.AutoInitDictionary(), null);
        var model = Newtonsoft.Json.Linq.JObject.Parse("{\"focus\":{\"aborted\":true}}");
        var actions = 0;
        var task = new MFAAvalonia.Helper.ValueType.MFATask
        {
            Count = 2,
            Action = () =>
            {
                actions++;
                focus.DisplayFocus(model, "Node.Action.Starting", "", onAborted: () => cancel.Cancel());
                return Task.CompletedTask;
            }
        };
        var result = await task.Run(cancel.Token);
        if (actions != 1 || !cancel.IsCancellationRequested ||
            result.Status != MFAAvalonia.Helper.ValueType.MFATask.MFATaskStatus.STOPPED)
            throw new Exception($"Focus abort did not stop repeated task: {actions}, {result}");
        // Exercise the actual processor callback as well: older GUI builds expose
        // FocusHandler's callback parameter but fail to connect it to their queue.
        Directory.SetCurrentDirectory(package);
        var processorType = typeof(MFAAvalonia.Extensions.MaaFW.MaaProcessor);
        processorType.Assembly.GetType("MFAAvalonia.App").GetProperty("Services")
            .SetValue(null, new HeadlessSettings());
        var processor = new MFAAvalonia.Extensions.MaaFW.MaaProcessor("phantom-focus-check");
        try
        {
            using var queueCancel = new CancellationTokenSource();
            processorType.GetProperty("CancellationTokenSource").SetValue(processor, queueCancel);
            processor.TaskQueue.Enqueue(new MFAAvalonia.Helper.ValueType.MFATask());
            var callback = processorType.GetMethod("HandleCallBack");
            var callbackType = callback.GetParameters()[1].ParameterType;
            var constructor = callbackType.GetConstructors().Single();
            var handleType = constructor.GetParameters()[2].ParameterType;
            var callbackArgs = constructor.Invoke(new object[]
            {
                "Node.Action.Starting", "{\"name\":\"PhantomJackpot\",\"focus\":{\"aborted\":true}}",
                Activator.CreateInstance(handleType)
            });
            callback.Invoke(processor, new object[] { null, callbackArgs });
            if (!queueCancel.IsCancellationRequested || processor.TaskQueue.Count != 0)
                throw new Exception("Compiled processor did not synchronously stop its queue from focus");
        }
        finally
        {
            processor.Dispose();
        }
        Console.WriteLine("GUI focus callback, queue cancellation and iteration stop passed.");
    }
}

// Only ShowHitDraw is read by the callback. Supply its false default without
// constructing the settings UI or initializing other application services.
class HeadlessSettings : IServiceProvider
{
    public object GetService(Type type) => type.Name == "GameSettingsUserControlModel"
        ? System.Runtime.CompilerServices.RuntimeHelpers.GetUninitializedObject(type)
        : throw new InvalidOperationException($"Unexpected UI service in headless check: {type.Name}");
}
