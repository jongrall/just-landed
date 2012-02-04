def text_to_html(text):
    def reindent(line):
        stripped_line = line.lstrip()
        num_leading_spaces = len(line) - len(stripped_line)
        leading_space = num_leading_spaces * '&nbsp;'
        return leading_space + stripped_line

    lines = [reindent(line).rstrip() for line in text.splitlines()]
    return '<br />'.join(lines)