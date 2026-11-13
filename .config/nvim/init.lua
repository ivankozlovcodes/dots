-- ~/.config/nvim/init.lua

-- Must be set before lazy loads any plugin, or <leader> maps bind to "\".
vim.g.mapleader = " "
vim.g.maplocalleader = " "

local lwpath = vim.fn.stdpath("data") .. "/lazy/lazy-workspaces.nvim"
if not (vim.uv or vim.loop).fs_stat(lwpath) then
  vim.fn.system({
    "git", "clone", "--filter=blob:none",
    "https://github.com/ivankozlovcodes/lazy-workspaces.nvim.git", lwpath,
  })
end
vim.opt.rtp:prepend(lwpath)

require("lazy-workspaces").setup({
  configs = {
    personal = { source = "~/git/nvim.conf.d" },
  },
})
