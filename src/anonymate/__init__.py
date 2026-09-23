"""anonymate: re-identification risk of dwelling data, against the whole Dutch housing stock.

Everything runs locally. Only the explicit ``ingest`` step downloads public registers; the
assessment itself never touches the network, so the addresses you assess never leave your machine.
"""
from .constraints import OneOf, Range
from .population import Population, Scope, Snapshot
from .qids import CATALOGUE, Knowledge, QidSpec, custom_qid
from .risk import Assessment, QidColumn, Status, Threshold, assess

__version__ = "0.1.0.dev0"

__all__ = [
    "Assessment", "CATALOGUE", "Knowledge", "OneOf", "Population", "QidColumn", "QidSpec",
    "Range", "Scope", "Snapshot", "Status", "Threshold", "assess", "custom_qid",
]
