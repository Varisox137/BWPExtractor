import pytest

from bwp_extractor.names import NameResolver, curated_relative


def test_verified_redirect_hash_and_resolution():
    resolver = NameResolver()
    resolver.add_path("redirect.nxs")
    resolved = resolver.resolve(0xF416002A)
    assert resolved.path == "redirect.nxs"
    assert resolved.source == "candidate"


def test_loads_explicit_mapping():
    resolver = NameResolver()
    resolver.load_mapping({"0123ABCD": "image/cards/1001.png"})
    resolved = resolver.resolve(0x0123ABCD)
    assert resolved.path == "image/cards/1001.png"
    assert resolved.source == "mapping"


def test_rejects_invalid_mapping_signature():
    resolver = NameResolver()
    with pytest.raises(ValueError, match="Invalid signature"):
        resolver.load_mapping({"not-a-hash": "image/cards/1001.png"})


def test_harvests_paths_and_preserves_unknown():
    resolver = NameResolver()
    resolver.harvest(b"image/cards/1001.png")
    signature = resolver.signature("image/cards/1001.png")
    assert resolver.resolve(signature).path == "image/cards/1001.png"
    unknown = resolver.resolve(123)
    assert unknown.path is None and unknown.source == "unresolved"


@pytest.mark.parametrize("path", ["../escape.png", "C:/escape.png", "/escape.png"])
def test_rejects_unsafe_paths(path: str):
    resolver = NameResolver()
    resolver.add_path(path)
    assert resolver.resolve(resolver.signature(path)).path is None


def test_curated_categories():
    assert curated_relative("image/cards/1001.png").startswith("cards/")
    assert curated_relative("gui/login/a.png").startswith("ui/")
    assert curated_relative("misc/a.png").startswith("other/")
