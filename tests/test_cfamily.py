"""C and C++: includes, methods defined outside their class (`void A::f()`),
template base classes, prototypes that aren't definitions, and headers
labeled C or C++ by what they contain."""

from codegraph.parser import parse_repo


def edges(result, kind):
    return {(e.src, e.dst) for e in result.edges if e.kind == kind}


def test_c_includes_and_calls_across_files(make_repo):
    repo = make_repo(
        {
            "src/list.h": "#ifndef LIST_H\n#define LIST_H\nint list_len(void);\n#endif\n",
            "src/list.c": '#include "list.h"\n\nint list_len(void) { return 0; }\n',
            "src/main.c": """#include <stdio.h>
#include "list.h"

int main(void) {
    return list_len();
}
""",
        }
    )
    result = parse_repo(repo)
    assert {dst for src, dst in edges(result, "imports") if src == "src/main.c"} == {"src/list.h"}
    # The header's prototype isn't a definition, so the call has exactly one target.
    assert "src/list.h::list_len" not in result.nodes
    assert ("src/main.c::main", "src/list.c::list_len") in edges(result, "calls")
    assert result.nodes["src/list.h"].language == "c"


def test_cpp_out_of_class_methods_templates_and_typed_calls(make_repo):
    repo = make_repo(
        {
            "include/sinks/base_sink.h": """#pragma once
template <typename Mutex>
class base_sink {
public:
    void log() { flush(); }
    virtual void flush() {}
};
""",
            "include/sinks/file_sink.h": """#pragma once
#include "base_sink.h"

class writer { public: void write(); };

template <typename Mutex>
class file_sink : public base_sink<Mutex> {
public:
    void flush();
};
""",
            "src/file_sink.cpp": """#include "sinks/file_sink.h"

void writer::write() {}

template <typename Mutex>
void file_sink<Mutex>::flush() {
    writer w;
    w.write();
}
""",
        }
    )
    result = parse_repo(repo)
    assert ("src/file_sink.cpp", "include/sinks/file_sink.h") in edges(result, "imports")  # by path suffix
    assert result.nodes["include/sinks/file_sink.h"].language == "cpp"
    assert ("include/sinks/file_sink.h::file_sink", "include/sinks/base_sink.h::base_sink") in edges(result, "inherits")
    # `void writer::write()` attaches to class writer, declared in another file.
    assert ("include/sinks/file_sink.h::writer", "src/file_sink.cpp::writer.write") in edges(result, "defines")
    calls = edges(result, "calls")
    assert ("src/file_sink.cpp::file_sink.flush", "src/file_sink.cpp::writer.write") in calls  # `writer w; w.write()`
    assert ("include/sinks/base_sink.h::base_sink.log", "include/sinks/base_sink.h::base_sink.flush") in calls
