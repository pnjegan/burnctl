# docs/homebrew/burnctl.rb
# Homebrew formula for burnctl
# Install via:
#   brew tap pnjegan/burnctl
#   brew install burnctl
#
# Or one-liner:
#   brew install pnjegan/burnctl/burnctl
#
# sha256 verified for v4.0.2 — regenerate on next tag bump with:
# curl -sL https://github.com/pnjegan/burnctl/archive/refs/tags/vX.Y.Z.tar.gz | sha256sum

class Burnctl < Formula
  desc "Real-time burn-rate monitor for Claude Code — tokens/min, $/hr, retry-loop detection"
  homepage "https://github.com/pnjegan/burnctl"
  url "https://github.com/pnjegan/burnctl/archive/refs/tags/v4.0.2.tar.gz"
  sha256 "9c90a81561f78829a38e8cd2691e38e2631e79b93250766c0cf1eece43bcc8d0"
  license "MIT"

  depends_on "python@3.11"
  depends_on "node" => :optional  # only needed for npx install method

  def install
    # Install Python scripts and supporting assets
    libexec.install Dir["*.py"]
    libexec.install "templates" if Dir.exist?("templates")
    libexec.install "tools"     if Dir.exist?("tools")
    libexec.install "static"    if Dir.exist?("static")
    libexec.install "bin"       if Dir.exist?("bin")

    # Create wrapper script
    (bin/"burnctl").write <<~EOS
      #!/bin/bash
      exec python3 "#{libexec}/cli.py" "$@"
    EOS
  end

  def caveats
    <<~EOS
      burnctl reads Claude Code session files from:
        macOS:   ~/.claude/projects/
        Linux:   ~/.claude/projects/

      To start the dashboard:
        burnctl dashboard

      To check live burn rate from the terminal:
        burnctl burnrate
        burnctl statusline

      All data stays local. Nothing is uploaded.
    EOS
  end

  test do
    system "#{bin}/burnctl", "--help"
  end
end
