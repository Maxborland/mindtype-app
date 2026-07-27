"""Override the upstream hook, which assumes distribution name `webrtcvad`.

MindType installs the maintained `webrtcvad-wheels` distribution. Runtime code
needs only its compiled extension; package metadata is not consulted.
"""

hiddenimports = ["_webrtcvad"]
