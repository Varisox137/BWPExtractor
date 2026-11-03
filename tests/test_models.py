from bwp_extractor.models import NameStatus, ResourceKind, Status


def test_status_values_are_stable():
    assert [s.value for s in Status] == [
        "success", "unsupported", "corrupt", "conversion_failed"
    ]
    assert NameStatus.UNRESOLVED.value == "unresolved"
    assert ResourceKind.KTX1.value == "ktx1"
