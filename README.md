### Check List
* `New-NetFirewallRule -DisplayName "BeamNG Port 25252" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 25252`
* ```docker compose up -d audiogen
    docker compose logs -f audiogen```