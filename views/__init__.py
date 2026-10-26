# views/__init__.py
"""
UI Views for the Volleyball Bot
"""

from .queue_views import QueueView, Queue2v2View, Queue3v3View, DuoQueueView, TrioQueueView, GroupInviteView, HighRankPositionView, Duo2v2SetupView, Trio3v3SetupView
from .leaderboard_views import LeaderboardView
from .stats_views import StatsView, CompareView
from .match_views import (
    MatchResultView, ReadyCheckView, RevertResultView,
    ResultWithTranscriptView, ManualWinnerSelectView, SwapPlayersModal
)
from .config_views import (
    ConfigHubView, build_hub_embed, build_admintools_hub_embed,
    GeneralSettingsView, StaffRolesSettingsView,
    BlacklistManageView, BlacklistReasonModal,
    SeasonManageView, SeasonStartModal, SeasonEndConfirmView, SeasonRemoveModal,
    EloRolesManageView, AddEloRoleModal, EloRoleSelectView, RemoveEloRoleModal,
    HighRankSettingsView, HighRankMmrModal, QueueChannelsView,
    AdminToolsHubView, EditEloModal, AdjustEloModal, ResetPlayerConfirmView,
    MatchCategoryModal, EloSettingsModal, MatchCleanupModal,
    AfkTimerModal, LogChannelView,
    AdminMatchEditView, EditMatchIdModal,
    ForceStartModal, EditStreaksModal,
)
from .region_views import RegionRoleView, build_region_embed

__all__ = [
    'QueueView', 'Queue2v2View', 'Queue3v3View', 'DuoQueueView', 'TrioQueueView',
    'GroupInviteView', 'HighRankPositionView', 'Duo2v2SetupView', 'Trio3v3SetupView',
    'LeaderboardView', 'StatsView', 'CompareView',
    'MatchResultView', 'ReadyCheckView', 'RevertResultView',
    'ResultWithTranscriptView', 'ManualWinnerSelectView', 'SwapPlayersModal',
    'ConfigHubView', 'build_hub_embed', 'build_admintools_hub_embed',
    'GeneralSettingsView', 'StaffRolesSettingsView',
    'BlacklistManageView', 'BlacklistReasonModal',
    'SeasonManageView', 'SeasonStartModal', 'SeasonEndConfirmView', 'SeasonRemoveModal',
    'EloRolesManageView', 'AddEloRoleModal', 'EloRoleSelectView', 'RemoveEloRoleModal',
    'HighRankSettingsView', 'HighRankMmrModal', 'QueueChannelsView',
    'AdminToolsHubView', 'EditEloModal', 'AdjustEloModal', 'ResetPlayerConfirmView',
    'MatchCategoryModal', 'EloSettingsModal', 'MatchCleanupModal',
    'AfkTimerModal', 'LogChannelView',
    'AdminMatchEditView', 'EditMatchIdModal',
    'ForceStartModal', 'EditStreaksModal',
    'RegionRoleView', 'build_region_embed',
]
