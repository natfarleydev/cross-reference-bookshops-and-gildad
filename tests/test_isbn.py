from origami import isbn


def test_valid_isbn10():
    assert isbn.is_valid_isbn10("080485310X")
    assert isbn.is_valid_isbn10("0-8048-5310-X")  # hyphens tolerated
    assert not isbn.is_valid_isbn10("0804853101")  # wrong check digit
    assert not isbn.is_valid_isbn10("12345")


def test_valid_isbn13():
    assert isbn.is_valid_isbn13("9780804853101")
    assert not isbn.is_valid_isbn13("9780804853100")
    assert not isbn.is_valid_isbn13("080485310X")


def test_isbn10_to_13_roundtrip():
    assert isbn.isbn10_to_13("080485310X") == "9780804853101"
    assert isbn.isbn10_to_13("invalid") is None


def test_to_isbn13_normalises():
    assert isbn.to_isbn13("080485310X") == "9780804853101"      # isbn10 -> 13
    assert isbn.to_isbn13("9780804853101") == "9780804853101"   # passthrough
    assert isbn.to_isbn13("978-0-8048-5310-1") == "9780804853101"


def test_to_isbn13_rejects_non_isbn():
    # Amazon non-book ASINs must be rejected so we never query Bookshop with junk.
    assert isbn.to_isbn13("B07XYZ1234") is None
    assert isbn.to_isbn13("") is None
    assert isbn.to_isbn13("notanisbn") is None


def test_looks_like_isbn():
    assert isbn.looks_like_isbn("080485310X")
    assert not isbn.looks_like_isbn("B0123ABCDE")
