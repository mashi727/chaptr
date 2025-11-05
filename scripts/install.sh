#!/usr/bin/env bash
# ==============================================================================
# Rehearsal Workflow インストールスクリプト
# ==============================================================================

set -euo pipefail

# 色定義
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m' # No Color

# ディレクトリ定義
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ZSH_FUNCTIONS_DIR="${HOME}/.config/zsh/functions"
CLAUDE_COMMANDS_DIR="${HOME}/.claude/commands"
ZSHRC="${HOME}/.zshrc"

# ログ関数
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

# ==============================================================================
# メイン処理
# ==============================================================================

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Rehearsal Workflow Installer"
echo "═══════════════════════════════════════════════════════════"
echo ""

# ------------------------------------------------------------------------------
# ステップ1: 依存関係チェック
# ------------------------------------------------------------------------------
log_step "Step 1/4: Checking dependencies..."
echo ""

check_command() {
    if command -v "$1" &> /dev/null; then
        log_info "✓ $1 found"
        return 0
    else
        log_warn "✗ $1 not found"
        return 1
    fi
}

MISSING_DEPS=0

check_command zsh || MISSING_DEPS=$((MISSING_DEPS + 1))
check_command ytdl-claude || { log_warn "  Install ytdl-claude from your source"; MISSING_DEPS=$((MISSING_DEPS + 1)); }
check_command whisper-remote || { log_warn "  Install whisper-remote from your source"; MISSING_DEPS=$((MISSING_DEPS + 1)); }
check_command luatex-pdf || { log_warn "  Install luatex-pdf from your source"; MISSING_DEPS=$((MISSING_DEPS + 1)); }

if [[ $MISSING_DEPS -gt 0 ]]; then
    echo ""
    log_warn "Some dependencies are missing. Installation will continue, but some features may not work."
    log_warn "Please install missing dependencies manually."
    echo ""
    read -p "Continue anyway? [y/N] " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_error "Installation cancelled."
        exit 1
    fi
fi

echo ""

# ------------------------------------------------------------------------------
# ステップ2: Zsh関数のインストール
# ------------------------------------------------------------------------------
log_step "Step 2/4: Installing Zsh functions..."
echo ""

mkdir -p "$ZSH_FUNCTIONS_DIR"

cp "${REPO_DIR}/bin/rehearsal-download" "$ZSH_FUNCTIONS_DIR/"
cp "${REPO_DIR}/bin/rehearsal-finalize" "$ZSH_FUNCTIONS_DIR/"
cp "${REPO_DIR}/bin/tex2chapters" "$ZSH_FUNCTIONS_DIR/"

chmod +x "${ZSH_FUNCTIONS_DIR}/rehearsal-download"
chmod +x "${ZSH_FUNCTIONS_DIR}/rehearsal-finalize"
chmod +x "${ZSH_FUNCTIONS_DIR}/tex2chapters"

log_info "✓ Zsh functions installed to: $ZSH_FUNCTIONS_DIR"
log_info "  - rehearsal-download"
log_info "  - rehearsal-finalize"
log_info "  - tex2chapters"
echo ""

# ------------------------------------------------------------------------------
# ステップ3: Claude Codeコマンドのインストール
# ------------------------------------------------------------------------------
log_step "Step 3/4: Installing Claude Code command..."
echo ""

mkdir -p "$CLAUDE_COMMANDS_DIR"

cp "${REPO_DIR}/claude/commands/rehearsal.md" "$CLAUDE_COMMANDS_DIR/"

log_info "✓ Claude command installed to: $CLAUDE_COMMANDS_DIR"
log_info "  - rehearsal.md"
echo ""

# ------------------------------------------------------------------------------
# ステップ4: .zshrc 設定の追加
# ------------------------------------------------------------------------------
log_step "Step 4/4: Configuring .zshrc..."
echo ""

CONFIG_LINE="fpath=(~/.config/zsh/functions \$fpath)"
AUTOLOAD_LINE="autoload -Uz tex2chapters rehearsal-download rehearsal-finalize"

if grep -q "rehearsal-download" "$ZSHRC" 2>/dev/null; then
    log_info "✓ .zshrc already configured"
else
    echo ""
    echo "The following lines need to be added to your ~/.zshrc:"
    echo ""
    echo -e "${YELLOW}  $CONFIG_LINE${NC}"
    echo -e "${YELLOW}  $AUTOLOAD_LINE${NC}"
    echo ""
    read -p "Add automatically? [y/N] " -n 1 -r
    echo ""

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "" >> "$ZSHRC"
        echo "# Rehearsal Workflow" >> "$ZSHRC"
        echo "$CONFIG_LINE" >> "$ZSHRC"
        echo "$AUTOLOAD_LINE" >> "$ZSHRC"
        log_info "✓ .zshrc updated"
    else
        log_warn "⚠ Please add manually to ~/.zshrc"
    fi
fi

echo ""

# ==============================================================================
# インストール完了
# ==============================================================================

echo "═══════════════════════════════════════════════════════════"
echo -e "${GREEN}  Installation Complete!${NC}"
echo "═══════════════════════════════════════════════════════════"
echo ""
log_info "Next steps:"
echo ""
echo "  1. Reload your Zsh configuration:"
echo -e "     ${GREEN}source ~/.zshrc${NC}"
echo ""
echo "  2. Test the installation:"
echo -e "     ${GREEN}rehearsal-download --help${NC}"
echo ""
echo "  3. Start using the workflow:"
echo -e "     ${GREEN}rehearsal-download \"https://youtu.be/VIDEO_ID\"${NC}"
echo ""
log_info "Documentation:"
echo "  - README:    ${REPO_DIR}/README.md"
echo "  - Docs:      ${REPO_DIR}/docs/"
echo ""
log_info "For troubleshooting, see: ${REPO_DIR}/docs/troubleshooting.md"
echo ""
