from tracefold.hashing import HashDomain, hash_canonical, sha256_domain
from tracefold.schemas.api import QueryEnvelope
from tracefold.schemas.source import SourceManifest, SourceManifestEntry


def test_domains_and_payloads_are_separated() -> None:
    assert sha256_domain(HashDomain.QUERY, b"x") != sha256_domain(HashDomain.SOURCE_MANIFEST, b"x")
    assert sha256_domain(HashDomain.QUERY, b"x") != sha256_domain(HashDomain.QUERY, b"y")


def test_query_and_manifest_hashes() -> None:
    query = QueryEnvelope(query=None)
    manifest = SourceManifest(
        entries=[
            SourceManifestEntry(
                source_id="src:0:x",
                input_ordinal=0,
                kind="text",
                authority="user",
                media_type="text/plain",
                raw_byte_hash="sha256:" + "a" * 64,
                byte_length=0,
            )
        ]
    )
    assert hash_canonical(HashDomain.QUERY, query).startswith("sha256:")
    assert hash_canonical(HashDomain.SOURCE_MANIFEST, manifest).startswith("sha256:")
