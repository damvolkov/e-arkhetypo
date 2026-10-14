# openhuman-ui — the desktop app's own React UI, built for the web from the same patched tree as the core
# (build.sh runs `vite build` in the source tree), served by nginx on loopback. Context: that app/dist.
FROM nginx:1.29-alpine
COPY dist/ /usr/share/nginx/html/
COPY --from=ui nginx.conf.template /etc/nginx/templates/default.conf.template
