# Code signing: getting rid of "Windows protected your PC"

Windows shows **"Windows protected your PC"** (this is called *SmartScreen*) for
programs that aren't **code‑signed**. Code signing is a digital signature that proves
who made the program and that nobody changed it after it was built.

The build on GitHub is already set up to sign `3D Print Backup.exe` automatically. It
just needs a signing account, which only **you** can create, because Microsoft has to
check your identity.

## What to expect (please read)

* **Cost:** Microsoft's *Azure Artifact Signing* (it used to be called *Trusted Signing*)
  Basic plan is about **US $9.99 a month**. Check the current price on Microsoft's site.
* **Who can sign up as a person:** individual developers in the **USA or Canada**.
  Companies can sign up in more countries.
* **The warning doesn't vanish on day one.** Signing changes the warning from
  "Unknown publisher" to **your name**, and Windows then builds up trust
  ("reputation") as people download and run signed versions without problems.
  After a while the warning stops appearing. Keep signing every release with the same
  account so the trust carries over.

## Step 1 – Create the signing account (Azure website)

1. Make a free Microsoft Azure account at <https://azure.microsoft.com> and add a
   payment method (this creates a *subscription*).
2. In the Azure portal (<https://portal.azure.com>), search for **Artifact Signing**
   and choose **Create**.
   * **Resource group:** create a new one, e.g. `codesigning`.
   * **Account name:** e.g. `codehound-signing`. *(Write this down → `SIGNING_ACCOUNT`.)*
   * **Region:** one close to you, e.g. *East US*.
   * **Pricing tier:** Basic.
3. Open the new account. On its **Overview** page, copy the **Account URI**, which looks like
   `https://eus.codesigning.azure.net/`. *(Write this down → `SIGNING_ENDPOINT`.)*

## Step 2 – Prove who you are

1. In the signing account, open **Access control (IAM)** → **Add role assignment** and
   give *yourself* the **Artifact Signing Identity Verifier** role.
2. Open **Identity validations** → **New identity** → **Public** → **Individual** and
   follow the steps. You'll be asked to verify with a government photo ID. Approval can
   take from a few hours to a few days.

## Step 3 – Make a certificate profile

1. Once your identity shows **Completed**, open **Certificate profiles** → **Create** →
   **Public Trust**.
2. Give it a name, e.g. `3dbackup`. *(Write this down → `SIGNING_PROFILE`.)*
3. Pick the identity you just validated.

## Step 4 – Give GitHub permission to sign

GitHub needs its own "login" to your signing account:

1. In the Azure portal search for **App registrations** → **New registration**.
   Name it `github-3dbackup-signing` and click **Register**.
2. On its Overview page copy:
   * **Directory (tenant) ID** → `AZURE_TENANT_ID`
   * **Application (client) ID** → `AZURE_CLIENT_ID`
3. Open **Certificates & secrets** → **New client secret** → copy the **Value** right
   away (it's only shown once) → `AZURE_CLIENT_SECRET`. Note when it expires; you'll
   need to make a new one then.
4. Go back to the signing account → **Access control (IAM)** → **Add role assignment** →
   **Artifact Signing Certificate Profile Signer** → assign it to
   `github-3dbackup-signing`.

## Step 5 – Put the details into GitHub

On GitHub open the repository → **Settings** → **Secrets and variables** → **Actions**.

**Secrets** tab (these are hidden; nobody can read them back):

| Name | Value |
|---|---|
| `AZURE_TENANT_ID` | Directory (tenant) ID |
| `AZURE_CLIENT_ID` | Application (client) ID |
| `AZURE_CLIENT_SECRET` | The client secret value |

**Variables** tab:

| Name | Value |
|---|---|
| `SIGNING_ENDPOINT` | The Account URI, e.g. `https://eus.codesigning.azure.net/` |
| `SIGNING_ACCOUNT` | The signing account name |
| `SIGNING_PROFILE` | The certificate profile name |

As soon as `SIGNING_ACCOUNT` is set, every build signs the `.exe` files and checks that
the signature is valid. If something is wrong, the build fails with a message instead of
quietly publishing an unsigned app.

## Step 6 – Publish a signed version

1. Change the version number in `backup3d/__init__.py` (e.g. `1.0.0` → `1.0.1`).
2. On GitHub: **Actions** → **Build Windows exe** → **Run workflow**, tick
   **Publish a release**.
3. Download the new zip, right‑click `3D Print Backup.exe` → **Properties** →
   **Digital Signatures**. Your name should be listed.

## Free alternative: SignPath Foundation

[SignPath Foundation](https://signpath.org) signs open‑source projects for free. The
catch: the program is signed as **"SignPath Foundation"** rather than your name, the
project needs an open‑source licence (this repository doesn't have one yet), and you
have to apply and be accepted. The build would need a different signing step.
