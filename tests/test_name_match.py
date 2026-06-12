"""Tests for src/etl/name_match.py"""

from src.etl.name_match import (
    _make_key,
    _strip_suffix,
    resolve_client_name,
    is_copay_client,
)


class TestMakeKey:
    def test_basic(self):
        assert _make_key("Baker, Joselyn") == "BAKER, JOSELYN"

    def test_strip_suffix(self):
        assert _make_key("Baker, Joselyn PCA") == "BAKER, JOSELYN"

    def test_strip_suffix_lpn(self):
        assert _make_key("Faulkner, Shanada LPN") == "FAULKNER, SHANADA"

    def test_collapse_spaces(self):
        assert _make_key("Baker,  Joselyn") == "BAKER, JOSELYN"

    def test_uppercase(self):
        assert _make_key("carroll, robert") == "CARROLL, ROBERT"


class TestStripSuffix:
    def test_pca(self):
        assert _strip_suffix("Carroll, Robert PCA") == "Carroll, Robert"

    def test_lpn(self):
        assert _strip_suffix("Carroll, Robert LPN") == "Carroll, Robert"

    def test_rn(self):
        assert _strip_suffix("Carroll, Robert RN") == "Carroll, Robert"

    def test_parenthesized_lpn(self):
        assert _strip_suffix("Carroll, Robert (LPN)") == "Carroll, Robert"

    def test_no_suffix(self):
        assert _strip_suffix("Carroll, Robert") == "Carroll, Robert"


class TestResolveClientName:
    def setup_method(self):
        self.mapping = {
            "BAKER, JOSELYN": "BAKER, JOSELYN",
            "CARROLL, ROBERT": "CARROLL, ROBERT",
            "FAULKNER, SHANADA": "FAULKNER, SHANADA",
            "NOT AVAILABLE CLIENT": None,
        }

    def test_exact_match(self):
        name, status = resolve_client_name("BAKER, JOSELYN", self.mapping)
        assert name == "BAKER, JOSELYN"
        assert status == "MATCHED"

    def test_match_with_suffix(self):
        name, status = resolve_client_name("Baker, Joselyn PCA", self.mapping)
        assert name == "BAKER, JOSELYN"
        assert status == "MATCHED"

    def test_not_available(self):
        name, status = resolve_client_name("NOT AVAILABLE CLIENT", self.mapping)
        assert name is None
        assert status == "NOT_AVAILABLE"

    def test_unmatched(self):
        name, status = resolve_client_name("UNKNOWN PERSON", self.mapping)
        assert name is None
        assert status == "UNMATCHED"


class TestIsCopayClient:
    def setup_method(self):
        self.copay_set = {"HARRIS, PATRICIA", "SMITH, JOHN"}

    def test_in_copay(self):
        assert is_copay_client("Harris, Patricia", self.copay_set) is True

    def test_in_copay_with_suffix(self):
        assert is_copay_client("Harris, Patricia PCA", self.copay_set) is True

    def test_not_in_copay(self):
        assert is_copay_client("Jones, Mark", self.copay_set) is False
