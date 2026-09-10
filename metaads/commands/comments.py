"""Command: comments (read-only) — what people wrote under an ad.

Engagement counts come back from Insights, but the text does not, and the text
is where the answer usually is: a market that reacts and saves and never buys
tends to say why in the comments.

Three things make this edge different from the rest of the CLI:

1. The post ID is not the ad ID. An ad points at a creative, and the creative
   carries `effective_object_story_id` — the dark post Meta generated for it.
   That is what has comments; the ad itself has none.
2. A user or system-user token is refused here by design (error 190, subcode
   2069032). The edge wants the **Page access token**, which is fetched from
   the page itself and never stored.
3. Reading them additionally needs `pages_read_user_content` on the token.
   Without it Meta answers 10 / "Permission denied" — see the hint below.
"""

from __future__ import annotations

from metaads import api
from metaads.formatting import _die, _err, _output_json

COMMENT_FIELDS = "id,message,from,created_time,like_count,comment_count"
REPLY_FIELDS = "id,message,from,created_time,like_count"

PERMISSION_HINT = (
    "Chybí oprávnění `pages_read_user_content`.\n"
    "  Přidej ho systémovému uživateli v Business Settings → Users → System Users\n"
    "  (u té stránky, které reklama patří) a vygeneruj token znovu.\n"
    "  Scope `pages_read_engagement` na komentáře nestačí — dá jen souhrnná čísla."
)


def _post_id_from_ad(ad_id: str) -> str:
    """ad → creative → the post Meta actually published for it."""
    data = api._api_call("GET", ad_id, {"fields": "creative{id,effective_object_story_id}"})
    creative = data.get("creative") or {}
    post_id = creative.get("effective_object_story_id")
    if not post_id:
        _err(f"ERROR: Reklama {ad_id} nemá post, pod kterým by komentáře byly.")
        _die("  Kreativa nemá effective_object_story_id — bývá to u ještě nedoručených reklam.")
    return post_id


def _post_id_from_creative(creative_id: str) -> str:
    data = api._api_call("GET", creative_id, {"fields": "effective_object_story_id"})
    post_id = data.get("effective_object_story_id")
    if not post_id:
        _die(f"ERROR: Kreativa {creative_id} nemá effective_object_story_id.")
    return post_id


def _page_token(page_id: str) -> str:
    """The Page access token for `page_id`. Fetched per run, never written down."""
    data = api._api_call("GET", page_id, {"fields": "access_token"})
    token = data.get("access_token")
    if not token:
        _err(f"ERROR: Ke stránce {page_id} se nepodařilo získat Page access token.")
        _die("  Token musí mít `pages_show_list` a systémový uživatel přístup k té stránce.")
    return token


def _print_comment(c: dict, indent: str = "") -> None:
    author = (c.get("from") or {}).get("name") or "(neznámý)"
    when = (c.get("created_time") or "")[:16].replace("T", " ")
    likes = c.get("like_count") or 0
    replies = c.get("comment_count") or 0
    tail = []
    if likes:
        tail.append(f"{likes}× líbí")
    if replies:
        tail.append(f"{replies} odpovědí")
    meta = f"  [{', '.join(tail)}]" if tail else ""
    print(f"{indent}{when}  {author}{meta}")
    for line in (c.get("message") or "(bez textu)").splitlines() or ["(bez textu)"]:
        print(f"{indent}    {line}")


def cmd_comments(args) -> None:
    """Read comments under an ad's post."""
    given = [bool(args.ad_id), bool(args.creative_id), bool(args.post_id)]
    if sum(given) != 1:
        _die("ERROR: Zadej právě jedno z --ad-id / --creative-id / --post-id.")

    if args.post_id:
        post_id = args.post_id
    elif args.ad_id:
        post_id = _post_id_from_ad(args.ad_id)
    else:
        post_id = _post_id_from_creative(args.creative_id)

    # Dark-post IDs are `<page>_<post>`; the page half is who owns the comments.
    if "_" not in post_id:
        _die(f"ERROR: {post_id} nevypadá jako ID postu (čeká se `<page_id>_<post_id>`).")
    page_id = post_id.split("_", 1)[0]

    token = _page_token(page_id)

    fields = COMMENT_FIELDS
    if args.replies:
        fields += f",comments.limit(25){{{REPLY_FIELDS}}}"

    try:
        comments = api._paginate(
            f"{post_id}/comments",
            # `filter=stream` would flatten replies into the list; `toplevel`
            # keeps the tree so --replies can nest them under their parent.
            {"fields": fields, "limit": min(args.limit, 100), "filter": "toplevel",
             "order": "chronological"},
            max_items=args.limit,
            token=token,
        )
    except SystemExit:
        # The engine already said what Meta returned. The one failure worth
        # explaining further is the missing scope, because the fix is not
        # obvious from Meta's wording and is not a code problem.
        _err("")
        _err(PERMISSION_HINT)
        raise

    if args.json:
        _output_json(comments)
        return

    if not comments:
        print(f"Pod postem {post_id} zatím žádné komentáře.")
        return

    print(f"Post {post_id} — {len(comments)} komentářů\n")
    for c in comments:
        _print_comment(c)
        nested = ((c.get("comments") or {}).get("data")) or []
        for r in nested:
            _print_comment(r, indent="    │ ")
        print()
