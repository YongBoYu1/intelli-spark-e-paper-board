import os


def find_repo_root(start_dir):
    cur = os.path.abspath(start_dir)
    for _ in range(6):
        if os.path.isdir(os.path.join(cur, ".git")):
            return cur
        if os.path.isdir(os.path.join(cur, "third_party", "waveshare_ePaper")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return os.path.abspath(start_dir)


def get_waveshare_python_root(repo_root):
    env_root = os.environ.get("WAVESHARE_PYTHON_ROOT")
    if env_root:
        return env_root
    submodule_root = os.path.join(
        repo_root,
        "third_party",
        "waveshare_ePaper",
        "RaspberryPi_JetsonNano",
        "python",
    )
    return submodule_root


def get_waveshare_paths(repo_root):
    ws_root = get_waveshare_python_root(repo_root)
    picdir = os.path.join(ws_root, "pic")
    libdir = os.path.join(ws_root, "lib")
    return ws_root, picdir, libdir
