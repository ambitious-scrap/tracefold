import hashlib

from tracefold.schemas.api import QueryEnvelope
from tracefold.schemas.common import HashDomain, HashValue
from tracefold.schemas.source import SourceManifest
from tracefold.serialization import canonical_json_bytes

__all__ = ["HashDomain", "hash_canonical", "hash_query", "hash_source_manifest", "sha256_domain"]


def sha256_domain(domain: HashDomain, payload: bytes) -> HashValue:
    digest = hashlib.sha256(domain.value.encode("ascii") + b"\0" + payload).hexdigest()
    return f"sha256:{digest}"


def hash_canonical(domain: HashDomain, value: object) -> HashValue:
    return sha256_domain(domain, canonical_json_bytes(value))


def hash_query(query: QueryEnvelope) -> HashValue:
    return hash_canonical(HashDomain.QUERY, query)


def hash_source_manifest(manifest: SourceManifest) -> HashValue:
    return hash_canonical(HashDomain.SOURCE_MANIFEST, manifest)
