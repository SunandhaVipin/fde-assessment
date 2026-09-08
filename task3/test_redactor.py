from task3.redactor import (
    REDACTED,
    MAX_PENDING_CHARS,
    StreamingRedactor,
    redact_complete,
)


# ============================================================
# HELPER
# ============================================================

def run_stream(
    chunks: list[str],
) -> str:
    """
    Feed multiple chunks through StreamingRedactor and return
    the final client-visible response.
    """

    redactor = StreamingRedactor()

    output = ""


    for chunk in chunks:

        output += redactor.push(
            chunk
        )


    output += redactor.flush()


    return output


# ============================================================
# COMPLETE EMAIL
# ============================================================

def test_complete_email_redacted():

    result = redact_complete(
        "Email is john.smith@example.com"
    )


    assert (
        "john.smith@example.com"
        not in result
    )

    assert REDACTED in result


# ============================================================
# COMPLETE SSN
# ============================================================

def test_complete_ssn_redacted():

    result = redact_complete(
        "SSN is 123-45-6789"
    )


    assert (
        "123-45-6789"
        not in result
    )

    assert REDACTED in result


# ============================================================
# COMPLETE CREDIT CARD
# ============================================================

def test_complete_credit_card_redacted():

    result = redact_complete(
        "Card is 4111 1111 1111 1111"
    )


    assert (
        "4111 1111 1111 1111"
        not in result
    )

    assert REDACTED in result


# ============================================================
# EMAIL SPLIT ACROSS CHUNKS
# ============================================================

def test_email_split_across_chunks():

    result = run_stream(
        [
            "Customer email is john.",
            "smith@example.",
            "com. Thank you.",
        ]
    )


    assert (
        "john.smith@example.com"
        not in result
    )

    assert REDACTED in result

    assert "Thank you." in result


# ============================================================
# EMAIL SPLIT AT @
# ============================================================

def test_email_split_at_at_symbol():

    result = run_stream(
        [
            "Contact jane.doe",
            "@example",
            ".com today.",
        ]
    )


    assert (
        "jane.doe@example.com"
        not in result
    )

    assert REDACTED in result


# ============================================================
# SSN SPLIT ACROSS CHUNKS
# ============================================================

def test_ssn_split_across_chunks():

    result = run_stream(
        [
            "SSN: 123-",
            "45-",
            "6789 complete.",
        ]
    )


    assert (
        "123-45-6789"
        not in result
    )

    assert REDACTED in result


# ============================================================
# CREDIT CARD SPLIT ACROSS CHUNKS
# ============================================================

def test_credit_card_split_across_chunks():

    result = run_stream(
        [
            "Card: 4111 ",
            "1111 ",
            "1111 ",
            "1111.",
        ]
    )


    assert (
        "4111 1111 1111 1111"
        not in result
    )

    assert REDACTED in result


# ============================================================
# ALL THREE PII TYPES
# ============================================================

def test_multiple_pii_types():

    result = run_stream(
        [
            "Email: user@",
            "example.com ",
            "SSN: 123-45-",
            "6789 Card: 4111 1111 ",
            "1111 1111 end.",
        ]
    )


    assert (
        "user@example.com"
        not in result
    )

    assert (
        "123-45-6789"
        not in result
    )

    assert (
        "4111 1111 1111 1111"
        not in result
    )


    assert (
        result.count(REDACTED)
        >= 3
    )


# ============================================================
# NORMAL TEXT REMAINS UNCHANGED
# ============================================================

def test_normal_text_unchanged():

    original = (
        "Hello customer. "
        "Your order has shipped successfully."
    )


    result = run_stream(
        [
            "Hello customer. ",
            "Your order has shipped ",
            "successfully.",
        ]
    )


    assert result == original


# ============================================================
# MEMORY REMAINS BOUNDED
# ============================================================

def test_pending_buffer_is_bounded():

    redactor = StreamingRedactor()


    # Feed many pieces of data.

    for _ in range(500):

        redactor.push(
            "abcdefghij"
        )


        assert (
            len(redactor.pending)
            <= MAX_PENDING_CHARS
        )


# ============================================================
# SAFE PREFIX CAN STREAM BEFORE END
# ============================================================

def test_safe_text_can_be_emitted_before_flush():

    redactor = StreamingRedactor()


    first_output = redactor.push(
        "Hello customer. Your email is john."
    )


    # The normal prefix should be available before the stream
    # has ended.

    assert "Hello customer." in first_output


    # But the potentially sensitive suffix should not yet
    # have leaked.

    assert "john." not in first_output


# ============================================================
# NO RAW PII IN FINAL MOCK-LIKE STREAM
# ============================================================

def test_mock_provider_chunk_pattern():

    result = run_stream(
        [
            "Hello. Your registered email is john.",
            "smith@example.",
            "com. Your SSN is 123-45-",
            "6789. Your card is 4111 1111 ",
            "1111 1111. End of response.",
        ]
    )


    assert (
        "john.smith@example.com"
        not in result
    )

    assert (
        "123-45-6789"
        not in result
    )

    assert (
        "4111 1111 1111 1111"
        not in result
    )


    assert (
        result.count(REDACTED)
        >= 3
    )


    assert (
        "End of response."
        in result
    )