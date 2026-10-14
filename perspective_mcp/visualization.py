"""Structured tool output: Perspective viewer configs bound to tables hosted by the MCP server."""

from importlib.metadata import version
from importlib.resources import files
from string import Template
from typing import Any, Literal

from pydantic import BaseModel, Field

Plugin = Literal[
    "Datagrid",
    "Y Line",
    "Y Area",
    "Y Bar",
    "X Bar",
    "Y Scatter",
    "X/Y Scatter",
    "X/Y Line",
    "Candlestick",
    "OHLC",
    "Heatmap",
    "Treemap",
    "Sunburst",
]
Kind = Literal["chart", "table", "workspace"]
Layout = dict[str, Any]

VIEWER_PAGE = Template(files(__package__).joinpath("viewer.html").read_text())
PERSPECTIVE_VERSION = version("perspective-python")


class Panel(BaseModel):
    """A `<perspective-viewer>` config, as accepted by `viewer.restore()`."""

    table: str
    title: str
    plugin: Plugin = "Datagrid"
    columns: list[str] = []
    group_by: list[str] = []
    split_by: list[str] = []
    sort: list[tuple[str, Literal["asc", "desc"]]] = []
    columns_config: dict[str, dict[str, Any]] = {}


class Visualization(BaseModel):
    """Perspective panels rendered at `url`, streaming their tables from `websocket`."""

    id: str
    kind: Kind
    url: str
    websocket: str
    panels: dict[str, Panel]
    layout: Layout | None = Field(None, description="Workspace layout tree for `viewer.restoreWorkspace()`")
    summary: str

    def to_html(self) -> str:
        spec = self.model_dump_json(include={"websocket", "panels", "layout"}).replace("</", "<\\/")
        return VIEWER_PAGE.substitute(version=PERSPECTIVE_VERSION, spec=spec)


def kind_of(panels: dict[str, Panel], layout: Layout | None) -> Kind:
    if layout:
        return "workspace"
    return "table" if all(panel.plugin == "Datagrid" for panel in panels.values()) else "chart"


def tabs(*panels: str) -> Layout:
    return {"type": "tab-layout", "tabs": list(panels), "selected": 0}


def split(*children: Layout, orientation: Literal["horizontal", "vertical"], sizes: list[float]) -> Layout:
    return {"type": "split-layout", "orientation": orientation, "children": list(children), "sizes": sizes}
