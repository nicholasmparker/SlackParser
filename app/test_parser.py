from slack_parser import SlackMessageParser
import json

# Test message
test_message = {
    "from_url": "https://openloophealth.slack.com/archives/C06PKHVCE67/p1731161693874449?thread_ts=1731024617.596539&cid=C06PKHVCE67",
    "ts": "1731161693.874449",
    "author_id": "U05NBLLDQ4B",
    "channel_id": "C06PKHVCE67",
    "channel_team": "TQBU4GKJL",
    "channel_name": "wellsync-cma-provider",
    "is_msg_unfurl": True,
    "is_reply_unfurl": True,
    "message_blocks": [{
        "team": "TQBU4GKJL",
        "channel": "C06PKHVCE67",
        "ts": "1731161693.874449",
        "message": {
            "blocks": [{
                "type": "rich_text",
                "block_id": "M6Y7z",
                "elements": [{
                    "type": "rich_text_section",
                    "elements": [
                        {"type": "text", "text": "Hi, "},
                        {"type": "user", "user_id": "U07M5J7KYPQ"},
                        {"type": "text", "text": "! Upon checking, the patient has not yet responded to the previous email and has not attempted to call. I tried calling the patient again, but the call went to voicemail. I left a message and sent an email requesting that she call us back to confirm if she completed a COVID test. Thank you!"}
                    ]
                }]
            }]
        }
    }],
    "id": 1,
    "original_url": "https://openloophealth.slack.com/archives/C06PKHVCE67/p1731161693874449?thread_ts=1731024617.596539&cid=C06PKHVCE67",
    "fallback": "[November 9th, 2024 6:14 AM] joyce.menguito: Hi, <@U07M5J7KYPQ>! Upon checking, the patient has not yet responded to the previous email and has not attempted to call. I tried calling the patient again, but the call went to voicemail. I left a message and sent an email requesting that she call us back to confirm if she completed a COVID test. Thank you!",
    "text": "Hi, <@U07M5J7KYPQ>! Upon checking, the patient has not yet responded to the previous email and has not attempted to call. I tried calling the patient again, but the call went to voicemail. I left a message and sent an email requesting that she call us back to confirm if she completed a COVID test. Thank you!",
    "author_name": "Joyce Anne Lapie Menguito",
    "author_link": "https://openloophealth.slack.com/team/U05NBLLDQ4B",
    "author_icon": "https://avatars.slack-edge.com/2024-07-11/7429955322288_37a03e4152718d1a4db2_48.jpg",
    "author_subname": "Joyce Anne Lapie Menguito",
    "mrkdwn_in": ["text"]
}

def main():
    parser = SlackMessageParser()
    parsed = parser.parse_message(test_message)
    print("Parsed Message:")
    print(json.dumps(parsed, indent=2))

if __name__ == "__main__":
    main()
