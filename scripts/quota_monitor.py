"""Monitor YouTube API quota usage."""

from nichescope.services.youtube_api import youtube_api


def main():
    print(f"YouTube API Quota Status")
    print(f"========================")
    print(f"Used:      {youtube_api._quota_used:,} units")
    print(f"Remaining: {youtube_api.quota_remaining:,} units")
    print(f"Daily cap: {youtube_api._service is not None and 10_000 or 0:,} units")
    print()
    print("Quota costs per operation:")
    print("  search.list        = 100 units  (AVOID)")
    print("  channels.list      =   1 unit")
    print("  playlistItems.list =   1 unit")
    print("  videos.list        =   1 unit   (batch 50)")
    print("  commentThreads     =   1 unit")


if __name__ == "__main__":
    main()
