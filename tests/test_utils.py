from src.core.utils import file_to_data_url


def test_file_to_data_url_returns_png_data_url(tmp_path) -> None:
    png_path = tmp_path / "preview.png"
    png_path.write_bytes(b"\x89PNG\r\n\x1a\npreview")

    result = file_to_data_url(str(png_path), "image/png")

    assert result is not None
    assert result.startswith("data:image/png;base64,")
