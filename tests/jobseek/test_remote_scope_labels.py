from __future__ import annotations

from jobseek.public_shortlist.export import _remote_scope


def test_remote_scope_province_remote():
  loc = "Remote — Ontario"
  scope = _remote_scope(loc, "remote", ["Ontario"])
  assert scope == "province"


def test_remote_scope_canada_remote():
  loc = "Remote, Canada"
  scope = _remote_scope(loc, "remote", [])
  assert scope == "canada"


def test_remote_scope_local_hybrid():
  loc = "Toronto, ON (Hybrid)"
  scope = _remote_scope(loc, "hybrid", ["Ontario"])
  assert scope == "local"
