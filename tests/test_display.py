from zcli.display import format_console_message, prompt_text


def test_prompt_colors_name_session_and_marker():
    rendered = prompt_text("default")

    assert "\033[" in rendered
    assert "zcli" in rendered
    assert "(default)" in rendered
    assert ">>" in rendered
    assert rendered.endswith(" ")


def test_console_message_colors_only_the_leading_label():
    rendered = format_console_message("[read_file] file contents")

    assert rendered.startswith("\033[")
    assert "[read_file]" in rendered
    assert rendered.endswith(" file contents")
    assert format_console_message("ordinary response") == "ordinary response"


def test_console_message_colors_standalone_parenthesized_hint():
    rendered = format_console_message("(no todos)")

    assert rendered.startswith("\033[")
    assert "(no todos)" in rendered
