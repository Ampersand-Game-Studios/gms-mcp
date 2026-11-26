"""Lines the GameMaker runner writes to every game's log, whatever the game.

A game log opens with the runner's own start-up report (its banner, each data chunk it loads,
the graphics driver's capabilities, its preparation steps) and closes with its memory figures.
The lines are the same in every run of every project, so in a failed test's log tail they only
push out the game's own lines. They were taken from the logs of 405 macOS test runs across
seven projects: every line here appeared, word for word apart from numbers, in all seven.

Anything not matched here (the game's own output, a library's banner, a shader that failed to
compile, a runtime error) is kept. The full log stays on disk for gm_run_log.
"""

from __future__ import annotations

import re

_EXACT = frozenset(
    {
        "About to startroom",
        "Audio_Init()",
        "Code_Load()",
        "Create Error Form",
        "Create Load Form",
        "Create Window",
        "Debug Init Remote Interface",
        "Do The Work",
        "Done Extension_Initialize",
        "Done ObjectLists",
        "Done RenderStateManager",
        "Done g_EffectsManager.Init()",
        "Entering main loop.",
        "Finished PrepareGame()",
        "GR_D3D_Init()",
        "Game_Prepare()",
        "Get Header Information",
        "Get Resolution",
        "ID_STRG",
        "IO Init",
        "Init Graphics",
        "InitGMLFunctions",
        "LoadGameData()",
        "Object_Prepare()",
        "Part Create Textures",
        "Pause event has been registered for this frame",
        "Pause event has been unregistered",
        "PrepareGame()",
        "Process Messages",
        "Room_Prepare()",
        "Run_Start",
        "Script_Prepare()",
        "Splash!",
        "Sprite_InitTextures()",
        "Start Frame",
        "TimeLine_Prepare()",
        "Tileset_InitTextures()",
        "VARI_Load()",
        "VM Init",
        "Variable_Global_Init()",
    }
)

_PATTERNS = re.compile(
    "|".join(
        (
            r"\*+\.?",  # the banner's rules
            r"Game\.\.Math\.\.Graphic\.\..*",  # each runtime module as it initialises
            r"###game_end###-?\d+",
            r"RunnerLoadGame(?:\(\) -|:) .*",
            r"CommandLine: -game .*",
            r"Processing command line -game .*",
            r"####!!!!\$+ pwd - .*",
            r"YYG Game launching\. Game file: .*",
            r"Checking if INIFile exists at .*",
            r"INIFile .* Exists, loading\.+",
            r"Loaded File .*\(\d+\)",
            r"Reading File .* took \d+ ms",
            r"\*\s+GameMaker v[\d.]+\s+\*",
            r"\*\s+YoYo Games \w+ Runner V[\d.]+\s+\*",
            r"MemoryManager allocated: \d+",
            r"Process Chunk: \w{4}\s+\d+\s+\([\d.]+MB\)",
            r"OpenGL(?: GLSL)?: .*",
            r"OpenGL version - detected \S+",
            r"Extensions: GL_\w+.*",
            r"Anisotropic filtering supported, max aniso \d+",
            r"Attempting to set gamepadcount to \d+",
            r"Audio group \d+ -> Loaded",
            r"Collision Event time\(microsecs\)=\d+",
            r"CreateColPairs took .*",
            r"Script_Free called with \d+ and global \d+",
            r"initialise everything! \S+, \d+",
            r"(?:Total|Peak) memory used = \d+ \(0x[0-9a-fA-F]+\) bytes [\d.]+MB",
            r"Free memory = \d+ \(0x[0-9a-fA-F]+\) bytes [\d.]+MB",
            r"libYoYoGamepad\.dylib found at path .*",
            r"Decoding [\w.-]+\.\.\.",  # the runner decompressing each compressed sound at start-up
        )
    )
)


def is_runner_line(line: str) -> bool:
    """Whether ``line`` is part of the runner's own start-up or shut-down report."""
    text = line.strip()
    return text in _EXACT or _PATTERNS.fullmatch(text) is not None
