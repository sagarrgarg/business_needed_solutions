"""Jinja helpers for BNS print formats."""

import pyqrcode


def get_einvoice_qr_code(qr_text: str, size_px_per_module: int = 6) -> str:
	"""Return the IRP signed QR as a base64 PNG, built to stay readable when printed small.

	India Compliance's ``get_qr_code`` uses error correction H. A ~950 character signed QR
	then needs a version 34 symbol (153 modules), whose modules are only ~0.22 mm wide at a
	34 mm print size. Level M (15% recovery, the usual default for printed codes) needs
	version 25 (117 modules), so each module is ~30% larger at the same size and still
	scans after print blur. A higher pixel scale keeps module edges sharp in the PDF.
	"""
	if not qr_text:
		return ""
	return pyqrcode.create(qr_text, error="M").png_as_base64_str(scale=size_px_per_module, quiet_zone=1)
