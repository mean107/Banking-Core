{{- define "banking.kong" -}}
_format_version: '3.0'
services:
  - name: api
    url: http://api.banking.svc.cluster.local:8080
    read_timeout: 40000
    routes:
      - name: api
        paths: [/api]
        strip_path: false
  - name: websocket
    url: http://notification.banking.svc.cluster.local:8080
    routes:
      - name: websocket
        paths: [/ws]
        strip_path: false
{{- end -}}
