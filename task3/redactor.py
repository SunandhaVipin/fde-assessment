import regex


# ============================================================
# REPLACEMENT VALUE
# ============================================================

REDACTED = "[REDACTED]"


# ============================================================
# PII REGULAR EXPRESSIONS
# ============================================================
#
# We use the third-party "regex" package rather than Python's
# built-in "re" because regex supports:
#
#     partial=True
#
# This lets us recognize that the END of a received chunk
# might be the beginning of a sensitive value that continues
# in the next chunk.
#
# Example:
#
# chunk 1:
#     john.smith@
#
# chunk 2:
#     example.com
#
# We must not release "john.smith@" before seeing chunk 2.
# ============================================================


EMAIL_PATTERN = regex.compile(
    r"""
    (?ix)

    (?<![A-Z0-9._%+-])

    [A-Z0-9._%+-]{1,64}

    @

    [A-Z0-9.-]{1,63}

    \.

    [A-Z]{2,24}

    (?![A-Z0-9-])
    """,
    regex.VERBOSE | regex.IGNORECASE,
)


SSN_PATTERN = regex.compile(
    r"""
    (?<!\d)

    \d{3}
    -
    \d{2}
    -
    \d{4}

    (?!\d)
    """,
    regex.VERBOSE,
)


CREDIT_CARD_PATTERN = regex.compile(
    r"""
    (?<!\d)

    (?:\d[ -]?){12,15}
    \d

    (?!\d)
    """,
    regex.VERBOSE,
)


# All sensitive patterns we want to inspect.

PII_PATTERNS = [
    EMAIL_PATTERN,
    SSN_PATTERN,
    CREDIT_CARD_PATTERN,
]


# ============================================================
# BOUNDED STREAMING STATE
# ============================================================
#
# We never keep the entire generated response in memory.
#
# We only retain a short suffix that could potentially be the
# beginning of a PII value split across chunks.
#
# This protects memory usage even if the provider streams a
# very large response.
# ============================================================

MAX_PENDING_CHARS = 160


# ============================================================
# COMPLETE REDACTION
# ============================================================

def redact_complete(
    text: str,
) -> str:
    """
    Redact all COMPLETE PII values found inside text.

    This function does not handle chunk boundaries by itself.
    StreamingRedactor below handles that.
    """

    result = text

    result = EMAIL_PATTERN.sub(
        REDACTED,
        result,
    )

    result = SSN_PATTERN.sub(
        REDACTED,
        result,
    )

    result = CREDIT_CARD_PATTERN.sub(
        REDACTED,
        result,
    )

    return result


# ============================================================
# FIND A POSSIBLE PARTIAL PII SUFFIX
# ============================================================

def _earliest_partial_suffix_start(
    text: str,
) -> int | None:
    """
    Inspect the tail of text and determine whether any suffix
    could be the beginning of a PII pattern.

    Example:

        "Hello john.smith@"

    The suffix:

        "john.smith@"

    is not yet a complete email, but it could become:

        john.smith@example.com

    after the next streaming chunk arrives.

    Therefore we return the position where that risky suffix
    begins so StreamingRedactor can hold it temporarily.
    """

    if not text:
        return None


    # Only examine a bounded tail.
    #
    # This guarantees that our work does not grow with the
    # total size of the generated response.

    scan_start = max(
        0,
        len(text) - MAX_PENDING_CHARS,
    )


    earliest = None


    for start in range(
        scan_start,
        len(text),
    ):

        suffix = text[start:]


        for pattern in PII_PATTERNS:

            match = pattern.fullmatch(
                suffix,
                partial=True,
            )


            # If partial=True, the text could become a valid
            # complete match if future characters arrive.

            if (
                match is not None
                and match.partial
            ):

                if (
                    earliest is None
                    or start < earliest
                ):

                    earliest = start


    return earliest


# ============================================================
# STREAMING REDACTOR
# ============================================================

class StreamingRedactor:
    """
    Stateful streaming PII redactor.

    Usage:

        redactor = StreamingRedactor()

        output = redactor.push(chunk1)
        output += redactor.push(chunk2)
        output += redactor.flush()

    The class never needs the entire response.

    It only keeps a bounded pending suffix which might contain
    a PII value split across chunk boundaries.
    """


    def __init__(
        self,
    ) -> None:

        self.pending = ""


    # ========================================================
    # PUSH ONE STREAMING CHUNK
    # ========================================================

    def push(
        self,
        chunk: str,
    ) -> str:
        """
        Process one incoming provider chunk.

        Returns only text that is safe to immediately send to
        the client.

        Potentially-sensitive suffixes remain temporarily
        stored in self.pending.
        """

        if not chunk:
            return ""


        # Combine the small amount of text we held from the
        # previous chunk with the new chunk.

        combined = (
            self.pending
            + chunk
        )


        # We can now reconsider everything because a partial
        # match from the previous chunk may have become a
        # complete PII value.

        redacted = redact_complete(
            combined
        )


        # Determine whether the end of the redacted text could
        # still be the beginning of a PII value.

        partial_start = (
            _earliest_partial_suffix_start(
                redacted
            )
        )


        # ----------------------------------------------------
        # No possible partial PII at the end
        # ----------------------------------------------------

        if partial_start is None:

            self.pending = ""

            return redacted


        # ----------------------------------------------------
        # Safe part
        # ----------------------------------------------------

        safe_text = redacted[
            :partial_start
        ]


        # ----------------------------------------------------
        # Hold the uncertain suffix
        # ----------------------------------------------------

        self.pending = redacted[
            partial_start:
        ]


        # ----------------------------------------------------
        # Defensive memory bound
        # ----------------------------------------------------

        if (
            len(self.pending)
            > MAX_PENDING_CHARS
        ):

            excess_length = (
                len(self.pending)
                - MAX_PENDING_CHARS
            )

            safe_text += self.pending[
                :excess_length
            ]

            self.pending = self.pending[
                excess_length:
            ]


        return safe_text


    # ========================================================
    # END OF STREAM
    # ========================================================

    def flush(
        self,
    ) -> str:
        """
        Called when the upstream provider finishes streaming.

        At this point there are no future chunks, so whatever
        remains can be redacted one final time and released.
        """

        if not self.pending:
            return ""


        result = redact_complete(
            self.pending
        )


        self.pending = ""


        return result