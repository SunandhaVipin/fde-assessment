import regex




REDACTED = "[REDACTED]"





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



PII_PATTERNS = [
    EMAIL_PATTERN,
    SSN_PATTERN,
    CREDIT_CARD_PATTERN,
]




MAX_PENDING_CHARS = 160



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


   

        combined = (
            self.pending
            + chunk
        )


       

        redacted = redact_complete(
            combined
        )


    

        partial_start = (
            _earliest_partial_suffix_start(
                redacted
            )
        )


        

        if partial_start is None:

            self.pending = ""

            return redacted


       

        safe_text = redacted[
            :partial_start
        ]


       

        self.pending = redacted[
            partial_start:
        ]


    
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
