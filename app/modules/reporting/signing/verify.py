"""Verificación independiente de firmas PAdES: integridad, cadena de confianza y sello de tiempo."""
from __future__ import annotations

import io
from dataclasses import asdict, dataclass, field


@dataclass
class SignatureReport:
    field_name: str
    intact: bool                # el contenido firmado no fue alterado
    valid: bool                 # la firma criptográfica es válida
    trusted: bool               # la cadena llega a una raíz de confianza configurada
    covers_entire_file: bool    # no hay contenido añadido después de la firma
    signer: str
    timestamp_valid: bool | None
    bottom_line: bool
    notes: list[str] = field(default_factory=list)


def verify_pdf(pdf_bytes: bytes, trust_roots_pem: str | None) -> list[dict]:
    from pyhanko.keys import load_cert_from_pemder
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko.sign.validation.status import SignatureCoverageLevel
    from pyhanko_certvalidator import ValidationContext

    roots = []
    if trust_roots_pem:
        from asn1crypto import pem
        with open(trust_roots_pem, "rb") as fh:
            roots = [load_cert_from_pemder_bytes(der) for _, _, der in pem.unarmor(fh.read(), multiple=True)]
    vc = ValidationContext(trust_roots=roots) if roots else ValidationContext(allow_fetching=False)

    reader = PdfFileReader(io.BytesIO(pdf_bytes))
    results = []
    for sig in reader.embedded_signatures:
        st = validate_pdf_signature(sig, vc)
        notes = []
        if not roots:
            notes.append("Sin raíces de confianza configuradas: no se puede afirmar confianza en el emisor.")
        results.append(asdict(SignatureReport(
            field_name=sig.field_name, intact=bool(st.intact), valid=bool(st.valid), trusted=bool(st.trusted),
            covers_entire_file=(st.coverage == SignatureCoverageLevel.ENTIRE_FILE),
            signer=st.signing_cert.subject.human_friendly,
            timestamp_valid=(st.timestamp_validity.valid if getattr(st, "timestamp_validity", None) else None),
            bottom_line=bool(st.bottom_line), notes=notes)))
    return results


def load_cert_from_pemder_bytes(der: bytes):
    from asn1crypto import x509
    return x509.Certificate.load(der)
