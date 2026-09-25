# Copyright (c) 2026 PythonizeYAML contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Requirement 7: changing one value leaves everything else untouched."""

from __future__ import annotations

import pytest

import pythonizeyaml as py


@pytest.fixture
def rich_source(read_fixture):
    return read_fixture("rich.yaml")


def set_value(data, path, value):
    node = data
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return data


def assert_only_one_line_changed(source, output, old_line, new_line):
    """Every line but one must be byte-identical, including comments and blanks."""
    source_lines = source.splitlines()
    output_lines = output.splitlines()
    assert len(source_lines) == len(output_lines)
    replaced = 0
    for before, after in zip(source_lines, output_lines):
        if before == old_line:
            assert after == new_line
            replaced += 1
        else:
            assert after == before
    assert replaced == 1


def test_only_the_mutated_substring_changes(rich_source):
    data = py.load(rich_source)
    data["server"]["host"] = "example.com"
    output = py.dump(data)

    assert rich_source.count("localhost") == 1
    assert output == rich_source.replace("localhost", "example.com")
    assert "localhost" not in output
    assert "host: example.com\n" in output


def test_comments_and_indentation_survive_an_edit(rich_source):
    data = py.load(rich_source)
    data["server"]["host"] = "example.com"
    output = py.dump(data)

    assert_only_one_line_changed(rich_source, output, "  host: localhost", "  host: example.com")
    for comment in (
        "# Configuration for the example service",
        "# the service name",
        "# semantic version",
        "# Server settings",
        "# where to listen",
        "# end of config",
    ):
        assert comment in output


def test_other_scalars_keep_their_quoting_after_an_edit(rich_source):
    data = py.load(rich_source)
    data["server"]["port"] = 9090
    output = py.dump(data)

    assert_only_one_line_changed(rich_source, output, "  port: 8080", "  port: 9090")
    # ``version`` was not touched, so its double quotes must still be there.
    assert 'version: "1.0.0"' in output
    # ``verbose`` was not touched either; its redundant single quotes remain.
    assert "verbose: 'yes'" in output


def test_editing_a_boolean_keeps_the_layout(rich_source):
    data = py.load(rich_source)
    data["features"]["debug"] = True
    output = py.dump(data)

    assert_only_one_line_changed(rich_source, output, "  debug: false", "  debug: true")


def test_editing_a_quoted_scalar_keeps_its_quote_style(rich_source):
    data = py.load(rich_source)
    data["features"]["verbose"] = "no"
    output = py.dump(data)

    assert_only_one_line_changed(rich_source, output, "  verbose: 'yes'", "  verbose: 'no'")
    assert 'version: "1.0.0"' in output


def test_editing_a_top_level_scalar_keeps_the_comments(rich_source):
    data = py.load(rich_source)
    data["name"] = "renamed"
    output = py.dump(data)

    assert_only_one_line_changed(
        rich_source,
        output,
        "name: example  # the service name",
        "name: renamed  # the service name",
    )


def test_editing_a_list_entry_keeps_the_rest_of_the_document(rich_source):
    data = py.load(rich_source)
    data["server"]["tags"][0] = "frontend"
    output = py.dump(data)

    assert_only_one_line_changed(rich_source, output, "    - web", "    - frontend")
    assert "# where to listen" in output


def test_the_edited_document_reloads_with_the_new_value(rich_source):
    data = py.load(rich_source)
    data["server"]["host"] = "example.com"
    reloaded = py.load(py.dump(data))
    assert reloaded["server"]["host"] == "example.com"
    # Untouched values are unchanged in the data as well as in the text.
    assert reloaded["server"]["port"] == 8080
    assert reloaded["features"]["verbose"] == "yes"
    assert reloaded["version"] == "1.0.0"