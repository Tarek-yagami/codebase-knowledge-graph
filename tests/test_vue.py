"""Vue single-file components: the script is extracted as TypeScript under a
component node named after the file, and the template links to the child
components it renders and the handlers it calls."""

from codegraph.parser import parse_repo


def edges(result, kind):
    return {(e.src, e.dst) for e in result.edges if e.kind == kind}


SONG_LIST = """<template>
  <ul>
    <SongItem v-for="song in songs" :key="song.id" @play="onPlay" />
    <empty-state v-if="!songs.length" @retry="reload(true)" />
  </ul>
</template>

<script lang="ts" setup>
import SongItem from './SongItem.vue'
import EmptyState from './EmptyState.vue'
import { fetchSongs } from '@/api/songs'

const songs = fetchSongs()

const onPlay = () => reload(false)

function reload(force: boolean) {
  fetchSongs()
}
</script>
"""


def build(make_repo):
    return parse_repo(
        make_repo(
            {
                "tsconfig.json": '{"compilerOptions": {"paths": {"@/*": ["./src/*"]}}}',
                "src/api/songs.ts": "export function fetchSongs() { return [] }\n",
                "src/components/SongItem.vue": "<template><li /></template>\n",
                "src/components/EmptyState.vue": "<template><p /></template>\n<script setup>\n</script>\n",
                "src/components/SongList.vue": SONG_LIST,
            }
        )
    )


def test_component_owns_script_definitions_with_real_line_numbers(make_repo):
    result = build(make_repo)
    component = "src/components/SongList.vue::SongList"
    assert result.nodes[component].language == "vue"
    assert (component, f"{component}.reload") in edges(result, "defines")
    assert result.nodes[f"{component}.reload"].lineno == 17  # its line in the .vue file, not in the script block


def test_imports_resolve_to_vue_and_ts_files(make_repo):
    imports = {dst for src, dst in edges(build(make_repo), "imports") if src == "src/components/SongList.vue"}
    assert imports == {"src/components/SongItem.vue", "src/components/EmptyState.vue", "src/api/songs.ts"}


def test_template_links_children_handlers_and_setup_calls(make_repo):
    result = build(make_repo)
    component = "src/components/SongList.vue::SongList"
    component_calls = {dst for src, dst in edges(result, "calls") if src == component}
    assert component_calls == {
        "src/components/SongItem.vue::SongItem",  # <SongItem>
        "src/components/EmptyState.vue::EmptyState",  # <empty-state>, kebab-case
        f"{component}.onPlay",  # @play="onPlay"
        f"{component}.reload",  # @retry="reload(true)"
        "src/api/songs.ts::fetchSongs",  # top-level setup code
    }
    # Sibling functions in <script setup> resolve to each other.
    assert (f"{component}.onPlay", f"{component}.reload") in edges(result, "calls")


def test_options_api_methods_and_this_calls(make_repo):
    repo = make_repo(
        {
            "Player.vue": """<template>
  <button @click="play">Play</button>
</template>

<script>
export default {
  data() { return { playing: false } },
  mounted() { this.reset() },
  methods: {
    play() { this.reset(); this.log() },
    reset() {},
    log: function () {},
  },
}
</script>
"""
        }
    )
    result = parse_repo(repo)
    component = "Player.vue::Player"
    assert {dst for src, dst in edges(result, "defines") if src == component} == {
        f"{component}.data",
        f"{component}.mounted",
        f"{component}.play",
        f"{component}.reset",
        f"{component}.log",
    }
    calls = edges(result, "calls")
    assert (component, f"{component}.play") in calls  # @click="play"
    assert (f"{component}.mounted", f"{component}.reset") in calls
    assert {dst for src, dst in calls if src == f"{component}.play"} == {f"{component}.reset", f"{component}.log"}
