"""
Firma y sellado de tiempo de PDFs (PAdES) con pyHanko.

  - Firma visible + firma de documento (subfilter PAdES), SHA-256.
  - Sello de tiempo RFC 3161 de una TSA (configurable) -> nivel PAdES-B-T.
  - Clave privada: PKCS#12 protegido (desarrollo/pruebas) o HSM/token PKCS#11 (producción).
  - Firma incremental: el contenido original queda intacto y cualquier cambio posterior invalida la firma.
Certificado: debe emitirlo un Proveedor de Servicios de Certificación acreditado (SUSCERTE) para
sustentar la validez jurídica; confirmar con Legal el nivel requerido.
"""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from datetime import datetime, timezone


class SigningError(Exception):
    pass


@dataclass
class SignedPdf:
    pdf_bytes: bytes
    sha256_unsigned: str
    sha256_signed: str
    signer_subject: str
    cert_serial: str
    cert_sha256: str
    signed_at: datetime
    timestamp_embedded: bool
    tsa_url: str | None


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_signer(config: dict, role: str = "CONTRALOR"):
    """
    Construye el firmante según SIGNING_MODE. Imports diferidos: el módulo carga sin pyHanko instalado.
    role="GERENTE_CI" usa SIGNING_PKCS12_PATH_GERENTE / SIGNING_PKCS12_PASSPHRASE_FILE_GERENTE (certificado distinto).
    """
    from pyhanko.sign import signers

    suffix = "_GERENTE" if role == "GERENTE_CI" else ""
    mode = config.get("SIGNING_MODE", "pkcs12")
    if mode == "pkcs12":
        path, pass_file = config.get("SIGNING_PKCS12_PATH" + suffix), config.get("SIGNING_PKCS12_PASSPHRASE_FILE" + suffix)
        if not path or not pass_file:
            raise SigningError(f"Falta configurar SIGNING_PKCS12_PATH{suffix} / SIGNING_PKCS12_PASSPHRASE_FILE{suffix}")
        with open(pass_file, "rb") as fh:
            passphrase = fh.read().strip()
        signer = signers.SimpleSigner.load_pkcs12(pfx_file=path, passphrase=passphrase)
        if signer is None:
            raise SigningError("No se pudo cargar el certificado PKCS#12")
        return signer
    if mode == "pkcs11":
        from pyhanko.sign import pkcs11
        session = pkcs11.open_pkcs11_session(config["PKCS11_LIB"], user_pin=config["PKCS11_PIN"],
                                             token_label=config["PKCS11_TOKEN_LABEL"])
        return pkcs11.PKCS11Signer(session, cert_label=config["PKCS11_CERT_LABEL"],
                                   key_label=config["PKCS11_KEY_LABEL"])
    raise SigningError(f"SIGNING_MODE desconocido: {mode}")


def sign_pdf(pdf_bytes: bytes, signer, *, reason: str, location: str, signer_name: str,
             field_name: str = "FirmaContralor", tsa_url: str | None = None,
             box: tuple[int, int, int, int] = (57, 62, 312, 130), page: int = -1) -> SignedPdf:
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import fields, timestamps
    from pyhanko.sign.signers.pdf_signer import PdfSignatureMetadata, PdfSigner
    from pyhanko.stamp import TextStampStyle

    timestamper = timestamps.HTTPTimeStamper(tsa_url) if tsa_url else None
    meta = PdfSignatureMetadata(field_name=field_name, md_algorithm="sha256", reason=reason, location=location,
                                name=signer_name, subfilter=fields.SigSeedSubFilter.PADES,
                                embed_validation_info=False)
    stamp = TextStampStyle(stamp_text="Firmado electrónicamente por:\n%(signer)s\nFecha/hora: %(ts)s\n"
                                      + reason, border_width=1)
    pdf_signer = PdfSigner(meta, signer=signer, timestamper=timestamper, stamp_style=stamp,
                           new_field_spec=fields.SigFieldSpec(field_name, on_page=page, box=box))
    try:
        out = pdf_signer.sign_pdf(IncrementalPdfFileWriter(io.BytesIO(pdf_bytes)))
    except Exception as exc:  # noqa: BLE001
        raise SigningError(f"Fallo al firmar: {type(exc).__name__}: {exc}") from exc
    signed = out.getvalue()
    cert = signer.signing_cert
    return SignedPdf(signed, sha256_hex(pdf_bytes), sha256_hex(signed), cert.subject.human_friendly,
                     format(cert.serial_number, "x"), sha256_hex(cert.dump()), datetime.now(timezone.utc),
                     timestamper is not None, tsa_url)
