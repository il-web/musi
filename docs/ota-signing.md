# OTA signing — setup runbook

The device pulls code from GitHub and then runs `update.sh`, which holds sudo
rights. Without a signature check, **control of the GitHub account is control of
the device**. `musi.player.updater` therefore refuses to apply any commit that
does not carry a good GPG signature from a key the Pi trusts.

Until you finish the steps below, Settings → Updates will show
`Update rejected: no valid signature` and refuse to install. That is the check
working, not a bug.

---

## 1. On your dev machine — create a signing key

```sh
gpg --full-generate-key       # ed25519 or RSA 4096; use your real email
gpg --list-secret-keys --keyid-format=long
```

Note the long key ID (the part after `sec   ed25519/`).

## 2. Tell git to sign every commit

```sh
git config --global user.signingkey <KEYID>
git config --global commit.gpgsign true
git config --global tag.gpgsign true
```

On Windows, point git at the gpg that Git for Windows already ships — otherwise
a later Gpg4win install shadows it with a *separate keyring* holding different
keys, which is the classic Windows GPG headache:

```sh
git config --global gpg.program "C:/Program Files/Git/usr/bin/gpg.exe"
```

**Generating the key on Windows:** `gpg --quick-generate-key ...` needs a real
terminal. Run it in a Git Bash window, not through a tool or IDE shell — without
a controlling tty, pinentry fails with `cannot open 'no tty'`.

Verify it took:

```sh
git commit --allow-empty -m "test: signing"
git log --show-signature -1        # expect "Good signature from ..."
```

## 3. Export the public key

```sh
gpg --armor --export <KEYID> > musi-signing.pub
```

This file is public — it's safe to email, commit, or paste anywhere.

## 4. On the Pi — import and trust it

Copy the file over, from Windows:

```sh
scp musi-signing.pub musi@musi.local:~/
```

Then on the Pi. Trust is set with `--import-ownertrust` rather than the
interactive `gpg --edit-key` prompt, which is painful over SSH:

```sh
gpg --import ~/musi-signing.pub
echo "CE2574AF3AB61492EFC9A5D852BA31D3E4F34050:6:" | gpg --import-ownertrust
rm ~/musi-signing.pub
```

The `:6:` means ultimate trust, which is right here: it's your own key on your
own device, and `git verify-commit` treats a valid signature from an *untrusted*
key as a failure — importing alone is not enough.

Check it landed:

```sh
gpg --list-keys --keyid-format=long        # expect [ultimate] next to the uid
```

**Current key** (musi, generated 2026-08-07, expires 2028-08-06):

```
ed25519/52BA31D3E4F34050
CE2574AF3AB61492EFC9A5D852BA31D3E4F34050
Ilay <4ilayf@gmail.com>
```

## 5. Verify end to end

On the Pi, in the checkout:

```sh
git fetch
git verify-commit origin/main && echo "OTA will accept this"
```

Exit code 0 means Settings → Updates will now work.

---

## If you get locked out

If you lose the key, or the Pi's keyring is wiped, the device will refuse all
updates. Two ways back:

- **Preferred:** generate a new key, redo steps 2–4, and push one signed commit.
- **Escape hatch:** run the app once with `MUSI_ALLOW_UNSIGNED=1`. This disables
  the only defence against a repo compromise, so use it to recover and then
  remove it — never leave it set in the systemd unit.

## What this does and does not protect

**Protects against:** someone who gains push access to the GitHub repo — a
stolen token, a compromised account, a malicious PR merged by mistake. They can
change the code on GitHub, but the Pi will not run it.

**Does not protect against:** your own signing key being stolen from your dev
machine. If an attacker has the key, they can sign whatever they like.

**Pairs with:** the root-owned `update-root.sh` (see the comments in
`install.sh` §9c). Signing stops bad code arriving; the root-owned copy means
that even if bad code *does* arrive, it cannot rewrite what runs as root.
