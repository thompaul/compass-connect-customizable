# Two example deployments

`northway/` and `southline/` are complete, working configurations for two deployments that do
not exist. Both organisations are invented. Nothing here is legal advice, and the documents are
marked as examples in their own text so a copy that escapes into a real deployment says so.

They are here to be switched between. Everything a partner can change without touching source
differs between the two, so applying one and then the other to the same environment shows, in
one pass, what deployment-time configuration actually reaches:

|                        | Northway                          | Southline                              |
| ---------------------- | --------------------------------- | -------------------------------------- |
| Product name           | Northway                          | Southline                              |
| Country                | Northland                         | Sur                                    |
| Browser tab and `<meta>` | "Northway — find your next step"  | "Southline"                            |
| Logos, favicon, avatar | teal on deep green                | amber on maroon                        |
| Theme colours          | teal / deep green                 | amber / maroon                         |
| Footer                 | funder logo, contact address, attribution line | none of the three         |
| Languages              | English (UK), Swahili             | Spanish (Spain) by default, English    |
| Privacy policy         | one, English                      | two: English and Spanish               |
| Terms of use           | one, English                      | one, English only — so a Spanish reader gets the English page, and the console says why |
| FAQ                    | yes, so the menu entry and `/faq` exist | none, so neither does               |

The FAQ row is the one worth watching. Switching from Northway to Southline removes a route and
a navigation entry, not just some text.

## Using one

A kit is laid out the way a deployment's configuration directory is laid out:

```
northway/
  northway.json                     the configuration, layered over the shipped defaults
  assets/                           everything that gets served
    northway-logo-light.svg         a file an operator supplies, referenced from the JSON
    ...
    content/                        the documents the interface reads
      privacy-policy.md
      terms-of-use.md
      faq.md
```

To deploy one, copy `assets/` into your configuration directory beside your `.env.<realm>.<env>`
and `stack_config.<realm>.<env>.yaml`, then merge the JSON into that env file and upload:

```bash
cp -R config/examples/northway/assets /path/to/config-dir/
python3 config/inject-config.py \
    --config config/examples/northway/northway.json \
    --deployment-env /path/to/config-dir/.env.myrealm.dev
python3 iac/scripts/setup_env.py --realm-name myrealm --env-name dev \
    --config-files-dir /path/to/config-dir
```

Then run the deployment. The assets archive is uploaded beside the environment file, downloaded
by `prepare.py`, laid over the frontend bundle by `prepare_frontend.py`, and uploaded to the
bucket by `pulumi up`.

## Switching after a deployment is already running

The same three commands. Nothing is rebuilt: the frontend bundle that is downloaded is
partner-neutral, and everything in the table above is applied to it at deployment time. Replace
`assets/`, re-run `inject-config.py` and `setup_env.py`, and deploy again.

Two things to expect:

- **The documents change immediately.** `content/` is served with `no-store`, because a
  corrected privacy policy that goes on showing the old text to everyone who already read it is
  the worst case this mechanism has.
- **Logos and illustrations can take up to an hour.** They are served with the bucket's default
  cache lifetime, which is the right trade for a file requested on every page load. A hard
  reload shows the new one straight away; a returning visitor may see the old one for a while.

## Seeing one locally, without deploying

```bash
cp -R config/examples/northway/assets/content frontend-new/public/content
python3 config/inject-config.py --config config/examples/northway/northway.json
```

The second command writes `frontend-new/public/data/env.js`, including the list of documents it
finds in `public/content/`. `yarn start` then serves them. Remember to remove
`frontend-new/public/content` afterwards — it is ignored by git, but it will otherwise be picked
up by every local run.
