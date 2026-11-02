from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Decision(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    PASS: _ClassVar[Decision]
    HIDE: _ClassVar[Decision]
    SHOW: _ClassVar[Decision]
PASS: Decision
HIDE: Decision
SHOW: Decision

class Empty(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class Enabled(_message.Message):
    __slots__ = ("enabled",)
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    enabled: bool
    def __init__(self, enabled: _Optional[bool] = ...) -> None: ...

class Video(_message.Message):
    __slots__ = ("id", "title", "channel", "description", "published", "duration_seconds", "seen_at_ms", "thumbnail", "thumbnail_type", "thumbnail_url", "source", "short", "fields")
    class FieldsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    ID_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    PUBLISHED_FIELD_NUMBER: _ClassVar[int]
    DURATION_SECONDS_FIELD_NUMBER: _ClassVar[int]
    SEEN_AT_MS_FIELD_NUMBER: _ClassVar[int]
    THUMBNAIL_FIELD_NUMBER: _ClassVar[int]
    THUMBNAIL_TYPE_FIELD_NUMBER: _ClassVar[int]
    THUMBNAIL_URL_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    SHORT_FIELD_NUMBER: _ClassVar[int]
    FIELDS_FIELD_NUMBER: _ClassVar[int]
    id: str
    title: str
    channel: str
    description: str
    published: str
    duration_seconds: int
    seen_at_ms: int
    thumbnail: bytes
    thumbnail_type: str
    thumbnail_url: str
    source: str
    short: bool
    fields: _containers.ScalarMap[str, str]
    def __init__(self, id: _Optional[str] = ..., title: _Optional[str] = ..., channel: _Optional[str] = ..., description: _Optional[str] = ..., published: _Optional[str] = ..., duration_seconds: _Optional[int] = ..., seen_at_ms: _Optional[int] = ..., thumbnail: _Optional[bytes] = ..., thumbnail_type: _Optional[str] = ..., thumbnail_url: _Optional[str] = ..., source: _Optional[str] = ..., short: _Optional[bool] = ..., fields: _Optional[_Mapping[str, str]] = ...) -> None: ...

class Outcome(_message.Message):
    __slots__ = ("hidden", "decided_by", "why")
    HIDDEN_FIELD_NUMBER: _ClassVar[int]
    DECIDED_BY_FIELD_NUMBER: _ClassVar[int]
    WHY_FIELD_NUMBER: _ClassVar[int]
    hidden: bool
    decided_by: str
    why: str
    def __init__(self, hidden: _Optional[bool] = ..., decided_by: _Optional[str] = ..., why: _Optional[str] = ...) -> None: ...

class VideoEvent(_message.Message):
    __slots__ = ("video", "outcome")
    VIDEO_FIELD_NUMBER: _ClassVar[int]
    OUTCOME_FIELD_NUMBER: _ClassVar[int]
    video: Video
    outcome: Outcome
    def __init__(self, video: _Optional[_Union[Video, _Mapping]] = ..., outcome: _Optional[_Union[Outcome, _Mapping]] = ...) -> None: ...

class Shown(_message.Message):
    __slots__ = ("ids", "at_ms")
    IDS_FIELD_NUMBER: _ClassVar[int]
    AT_MS_FIELD_NUMBER: _ClassVar[int]
    ids: _containers.RepeatedScalarFieldContainer[str]
    at_ms: int
    def __init__(self, ids: _Optional[_Iterable[str]] = ..., at_ms: _Optional[int] = ...) -> None: ...

class Feedback(_message.Message):
    __slots__ = ("video", "like", "at_ms")
    VIDEO_FIELD_NUMBER: _ClassVar[int]
    LIKE_FIELD_NUMBER: _ClassVar[int]
    AT_MS_FIELD_NUMBER: _ClassVar[int]
    video: Video
    like: bool
    at_ms: int
    def __init__(self, video: _Optional[_Union[Video, _Mapping]] = ..., like: _Optional[bool] = ..., at_ms: _Optional[int] = ...) -> None: ...

class Caption(_message.Message):
    __slots__ = ("video_id", "start_ms", "end_ms", "text", "language", "auto")
    VIDEO_ID_FIELD_NUMBER: _ClassVar[int]
    START_MS_FIELD_NUMBER: _ClassVar[int]
    END_MS_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    LANGUAGE_FIELD_NUMBER: _ClassVar[int]
    AUTO_FIELD_NUMBER: _ClassVar[int]
    video_id: str
    start_ms: int
    end_ms: int
    text: str
    language: str
    auto: bool
    def __init__(self, video_id: _Optional[str] = ..., start_ms: _Optional[int] = ..., end_ms: _Optional[int] = ..., text: _Optional[str] = ..., language: _Optional[str] = ..., auto: _Optional[bool] = ...) -> None: ...

class VideosRequest(_message.Message):
    __slots__ = ("limit", "thumbnails")
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    THUMBNAILS_FIELD_NUMBER: _ClassVar[int]
    limit: int
    thumbnails: bool
    def __init__(self, limit: _Optional[int] = ..., thumbnails: _Optional[bool] = ...) -> None: ...

class VideoEvents(_message.Message):
    __slots__ = ("events",)
    EVENTS_FIELD_NUMBER: _ClassVar[int]
    events: _containers.RepeatedCompositeFieldContainer[VideoEvent]
    def __init__(self, events: _Optional[_Iterable[_Union[VideoEvent, _Mapping]]] = ...) -> None: ...

class Stage(_message.Message):
    __slots__ = ("id", "kind", "config")
    ID_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    id: str
    kind: str
    config: _struct_pb2.Struct
    def __init__(self, id: _Optional[str] = ..., kind: _Optional[str] = ..., config: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

class Pipeline(_message.Message):
    __slots__ = ("stages", "kinds")
    STAGES_FIELD_NUMBER: _ClassVar[int]
    KINDS_FIELD_NUMBER: _ClassVar[int]
    stages: _containers.RepeatedCompositeFieldContainer[Stage]
    kinds: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, stages: _Optional[_Iterable[_Union[Stage, _Mapping]]] = ..., kinds: _Optional[_Iterable[str]] = ...) -> None: ...

class StageResult(_message.Message):
    __slots__ = ("decision", "why", "fields")
    class FieldsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    DECISION_FIELD_NUMBER: _ClassVar[int]
    WHY_FIELD_NUMBER: _ClassVar[int]
    FIELDS_FIELD_NUMBER: _ClassVar[int]
    decision: Decision
    why: str
    fields: _containers.ScalarMap[str, str]
    def __init__(self, decision: _Optional[_Union[Decision, str]] = ..., why: _Optional[str] = ..., fields: _Optional[_Mapping[str, str]] = ...) -> None: ...

class StageRequest(_message.Message):
    __slots__ = ("id", "config", "videos")
    ID_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    VIDEOS_FIELD_NUMBER: _ClassVar[int]
    id: int
    config: _struct_pb2.Struct
    videos: _containers.RepeatedCompositeFieldContainer[Video]
    def __init__(self, id: _Optional[int] = ..., config: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., videos: _Optional[_Iterable[_Union[Video, _Mapping]]] = ...) -> None: ...

class StageHello(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class StageReply(_message.Message):
    __slots__ = ("id", "results")
    ID_FIELD_NUMBER: _ClassVar[int]
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    id: int
    results: _containers.RepeatedCompositeFieldContainer[StageResult]
    def __init__(self, id: _Optional[int] = ..., results: _Optional[_Iterable[_Union[StageResult, _Mapping]]] = ...) -> None: ...

class StageMessage(_message.Message):
    __slots__ = ("hello", "reply")
    HELLO_FIELD_NUMBER: _ClassVar[int]
    REPLY_FIELD_NUMBER: _ClassVar[int]
    hello: StageHello
    reply: StageReply
    def __init__(self, hello: _Optional[_Union[StageHello, _Mapping]] = ..., reply: _Optional[_Union[StageReply, _Mapping]] = ...) -> None: ...

class Filters(_message.Message):
    __slots__ = ("filters",)
    FILTERS_FIELD_NUMBER: _ClassVar[int]
    filters: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, filters: _Optional[_Iterable[str]] = ...) -> None: ...

class Stats(_message.Message):
    __slots__ = ("checked", "hidden", "hidden_by_filter", "hidden_by_stage", "likes", "dislikes", "learning")
    class HiddenByFilterEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    class HiddenByStageEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    CHECKED_FIELD_NUMBER: _ClassVar[int]
    HIDDEN_FIELD_NUMBER: _ClassVar[int]
    HIDDEN_BY_FILTER_FIELD_NUMBER: _ClassVar[int]
    HIDDEN_BY_STAGE_FIELD_NUMBER: _ClassVar[int]
    LIKES_FIELD_NUMBER: _ClassVar[int]
    DISLIKES_FIELD_NUMBER: _ClassVar[int]
    LEARNING_FIELD_NUMBER: _ClassVar[int]
    checked: int
    hidden: int
    hidden_by_filter: _containers.ScalarMap[str, int]
    hidden_by_stage: _containers.ScalarMap[str, int]
    likes: int
    dislikes: int
    learning: bool
    def __init__(self, checked: _Optional[int] = ..., hidden: _Optional[int] = ..., hidden_by_filter: _Optional[_Mapping[str, int]] = ..., hidden_by_stage: _Optional[_Mapping[str, int]] = ..., likes: _Optional[int] = ..., dislikes: _Optional[int] = ..., learning: _Optional[bool] = ...) -> None: ...

class Hidden(_message.Message):
    __slots__ = ("id", "title", "channel", "why", "stage")
    ID_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_FIELD_NUMBER: _ClassVar[int]
    WHY_FIELD_NUMBER: _ClassVar[int]
    STAGE_FIELD_NUMBER: _ClassVar[int]
    id: str
    title: str
    channel: str
    why: str
    stage: str
    def __init__(self, id: _Optional[str] = ..., title: _Optional[str] = ..., channel: _Optional[str] = ..., why: _Optional[str] = ..., stage: _Optional[str] = ...) -> None: ...

class State(_message.Message):
    __slots__ = ("connected", "enabled", "filters", "stages", "apps", "stats", "recent")
    CONNECTED_FIELD_NUMBER: _ClassVar[int]
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    FILTERS_FIELD_NUMBER: _ClassVar[int]
    STAGES_FIELD_NUMBER: _ClassVar[int]
    APPS_FIELD_NUMBER: _ClassVar[int]
    STATS_FIELD_NUMBER: _ClassVar[int]
    RECENT_FIELD_NUMBER: _ClassVar[int]
    connected: bool
    enabled: bool
    filters: _containers.RepeatedScalarFieldContainer[str]
    stages: _containers.RepeatedScalarFieldContainer[str]
    apps: _containers.RepeatedScalarFieldContainer[str]
    stats: Stats
    recent: _containers.RepeatedCompositeFieldContainer[Hidden]
    def __init__(self, connected: _Optional[bool] = ..., enabled: _Optional[bool] = ..., filters: _Optional[_Iterable[str]] = ..., stages: _Optional[_Iterable[str]] = ..., apps: _Optional[_Iterable[str]] = ..., stats: _Optional[_Union[Stats, _Mapping]] = ..., recent: _Optional[_Iterable[_Union[Hidden, _Mapping]]] = ...) -> None: ...

class TestRequest(_message.Message):
    __slots__ = ("videos",)
    VIDEOS_FIELD_NUMBER: _ClassVar[int]
    videos: _containers.RepeatedCompositeFieldContainer[Video]
    def __init__(self, videos: _Optional[_Iterable[_Union[Video, _Mapping]]] = ...) -> None: ...

class StageTrace(_message.Message):
    __slots__ = ("stage", "decision", "why")
    STAGE_FIELD_NUMBER: _ClassVar[int]
    DECISION_FIELD_NUMBER: _ClassVar[int]
    WHY_FIELD_NUMBER: _ClassVar[int]
    stage: str
    decision: str
    why: str
    def __init__(self, stage: _Optional[str] = ..., decision: _Optional[str] = ..., why: _Optional[str] = ...) -> None: ...

class TestResult(_message.Message):
    __slots__ = ("id", "outcome", "fields", "trace")
    class FieldsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    ID_FIELD_NUMBER: _ClassVar[int]
    OUTCOME_FIELD_NUMBER: _ClassVar[int]
    FIELDS_FIELD_NUMBER: _ClassVar[int]
    TRACE_FIELD_NUMBER: _ClassVar[int]
    id: str
    outcome: Outcome
    fields: _containers.ScalarMap[str, str]
    trace: _containers.RepeatedCompositeFieldContainer[StageTrace]
    def __init__(self, id: _Optional[str] = ..., outcome: _Optional[_Union[Outcome, _Mapping]] = ..., fields: _Optional[_Mapping[str, str]] = ..., trace: _Optional[_Iterable[_Union[StageTrace, _Mapping]]] = ...) -> None: ...

class TestResults(_message.Message):
    __slots__ = ("results", "ms")
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    MS_FIELD_NUMBER: _ClassVar[int]
    results: _containers.RepeatedCompositeFieldContainer[TestResult]
    ms: float
    def __init__(self, results: _Optional[_Iterable[_Union[TestResult, _Mapping]]] = ..., ms: _Optional[float] = ...) -> None: ...

class Panel(_message.Message):
    __slots__ = ("id", "title", "blocks")
    ID_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    BLOCKS_FIELD_NUMBER: _ClassVar[int]
    id: str
    title: str
    blocks: _containers.RepeatedCompositeFieldContainer[Block]
    def __init__(self, id: _Optional[str] = ..., title: _Optional[str] = ..., blocks: _Optional[_Iterable[_Union[Block, _Mapping]]] = ...) -> None: ...

class Block(_message.Message):
    __slots__ = ("text", "stats", "bars", "table", "button")
    TEXT_FIELD_NUMBER: _ClassVar[int]
    STATS_FIELD_NUMBER: _ClassVar[int]
    BARS_FIELD_NUMBER: _ClassVar[int]
    TABLE_FIELD_NUMBER: _ClassVar[int]
    BUTTON_FIELD_NUMBER: _ClassVar[int]
    text: str
    stats: StatGrid
    bars: BarList
    table: Table
    button: str
    def __init__(self, text: _Optional[str] = ..., stats: _Optional[_Union[StatGrid, _Mapping]] = ..., bars: _Optional[_Union[BarList, _Mapping]] = ..., table: _Optional[_Union[Table, _Mapping]] = ..., button: _Optional[str] = ...) -> None: ...

class Stat(_message.Message):
    __slots__ = ("label", "value")
    LABEL_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    label: str
    value: str
    def __init__(self, label: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...

class StatGrid(_message.Message):
    __slots__ = ("stats",)
    STATS_FIELD_NUMBER: _ClassVar[int]
    stats: _containers.RepeatedCompositeFieldContainer[Stat]
    def __init__(self, stats: _Optional[_Iterable[_Union[Stat, _Mapping]]] = ...) -> None: ...

class Bar(_message.Message):
    __slots__ = ("label", "value")
    LABEL_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    label: str
    value: float
    def __init__(self, label: _Optional[str] = ..., value: _Optional[float] = ...) -> None: ...

class BarList(_message.Message):
    __slots__ = ("bars",)
    BARS_FIELD_NUMBER: _ClassVar[int]
    bars: _containers.RepeatedCompositeFieldContainer[Bar]
    def __init__(self, bars: _Optional[_Iterable[_Union[Bar, _Mapping]]] = ...) -> None: ...

class Row(_message.Message):
    __slots__ = ("cells",)
    CELLS_FIELD_NUMBER: _ClassVar[int]
    cells: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, cells: _Optional[_Iterable[str]] = ...) -> None: ...

class Table(_message.Message):
    __slots__ = ("columns", "rows")
    COLUMNS_FIELD_NUMBER: _ClassVar[int]
    ROWS_FIELD_NUMBER: _ClassVar[int]
    columns: _containers.RepeatedScalarFieldContainer[str]
    rows: _containers.RepeatedCompositeFieldContainer[Row]
    def __init__(self, columns: _Optional[_Iterable[str]] = ..., rows: _Optional[_Iterable[_Union[Row, _Mapping]]] = ...) -> None: ...

class PanelEvent(_message.Message):
    __slots__ = ("panel", "button")
    PANEL_FIELD_NUMBER: _ClassVar[int]
    BUTTON_FIELD_NUMBER: _ClassVar[int]
    panel: str
    button: str
    def __init__(self, panel: _Optional[str] = ..., button: _Optional[str] = ...) -> None: ...

class TimingsRequest(_message.Message):
    __slots__ = ("reset",)
    RESET_FIELD_NUMBER: _ClassVar[int]
    reset: bool
    def __init__(self, reset: _Optional[bool] = ...) -> None: ...

class Timing(_message.Message):
    __slots__ = ("name", "count", "mean_ms", "p50_ms", "p95_ms", "max_ms", "last_ms")
    NAME_FIELD_NUMBER: _ClassVar[int]
    COUNT_FIELD_NUMBER: _ClassVar[int]
    MEAN_MS_FIELD_NUMBER: _ClassVar[int]
    P50_MS_FIELD_NUMBER: _ClassVar[int]
    P95_MS_FIELD_NUMBER: _ClassVar[int]
    MAX_MS_FIELD_NUMBER: _ClassVar[int]
    LAST_MS_FIELD_NUMBER: _ClassVar[int]
    name: str
    count: int
    mean_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float
    last_ms: float
    def __init__(self, name: _Optional[str] = ..., count: _Optional[int] = ..., mean_ms: _Optional[float] = ..., p50_ms: _Optional[float] = ..., p95_ms: _Optional[float] = ..., max_ms: _Optional[float] = ..., last_ms: _Optional[float] = ...) -> None: ...

class Timings(_message.Message):
    __slots__ = ("timings",)
    TIMINGS_FIELD_NUMBER: _ClassVar[int]
    timings: _containers.RepeatedCompositeFieldContainer[Timing]
    def __init__(self, timings: _Optional[_Iterable[_Union[Timing, _Mapping]]] = ...) -> None: ...
