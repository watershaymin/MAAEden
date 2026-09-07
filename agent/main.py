import sys

from maa.agent.agent_server import AgentServer
from maa.toolkit import Toolkit

import my_action
import my_reco
import navigation
import menas_trial
import dungeons
import monthly_trial
import monthly_dungeons
import cat_diary

AgentServer.custom_action("NavigationMove")(navigation.NavigationMove)
AgentServer.custom_action("MenasTrial")(menas_trial.MenasTrial)
AgentServer.custom_action("NavigationBaruokiRoute")(navigation.NavigationBaruokiRoute)
AgentServer.custom_action("DungeonSkip")(dungeons.DungeonSkip)
AgentServer.custom_action("DungeonDismissDetail")(dungeons.DungeonDismissDetail)
AgentServer.custom_action("MonthlyStarTrial")(monthly_trial.MonthlyStarTrial)
AgentServer.custom_action("MonthlyTrialDungeons")(monthly_dungeons.MonthlyTrialDungeons)
AgentServer.custom_action("CatDiary")(cat_diary.CatDiary)
AgentServer.custom_recognition("DungeonMenuReady")(dungeons.DungeonMenuRecognition)


def main():
    Toolkit.init_option("./")

    if len(sys.argv) < 2:
        print("Usage: python main.py <socket_id>")
        print("socket_id is provided by AgentIdentifier.")
        sys.exit(1)
        
    socket_id = sys.argv[-1]

    AgentServer.start_up(socket_id)
    AgentServer.join()
    AgentServer.shut_down()


if __name__ == "__main__":
    main()
