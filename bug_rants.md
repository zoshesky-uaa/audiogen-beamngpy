#### Bug #1:
 Crash appears to be in the position and audiorecorder, in reference to position I saw this occur:
```shell
Flushed chunk to Zarr: frames 7680 to 8191
CE(1), TE(0): Starting light follow at vehicle frame 17724, at distance 1846.60 m.
Flushed chunk to Zarr: frames 7680 to 8191
CE(1), TE(0): Starting light follow at vehicle frame 17724, at distance 1846.60 m.
Flushed chunk to Zarr: frames 7680 to 8191
Flushed chunk to Zarr: frames 7680 to 8191
Flushed chunk to Zarr: frames 7680 to 8191
Flushed chunk to Zarr: frames 7680 to 8191
Flushed chunk to Zarr: frames 7680 to 8191
Flushed chunk to Zarr: frames 7680 to 8191
Flushed chunk to Zarr: frames 7680 to 8191
CE(1), TE(0): Starting light follow at vehicle frame 17724, at distance 1846.60 m.
Flushed chunk to Zarr: frames 7680 to 8191
CE(1), TE(0): Starting light follow at vehicle frame 17724, at distance 1846.60 m.
Flushed chunk to Zarr: frames 7680 to 8191
CE(1), TE(0): Starting light follow at vehicle frame 17724, at distance 1846.60 m.
Flushed chunk to Zarr: frames 7680 to 8191
CE(1), TE(0): Starting light follow at vehicle frame 17724, at distance 1846.60 m.
Flushed chunk to Zarr: frames 7680 to 8191
CE(1), TE(0): Starting light follow at vehicle frame 17724, at distance 1846.60 m.
Flushed chunk to Zarr: frames 7680 to 8191
Flushed chunk to Zarr: frames 7680 to 8191
CE(1), TE(0): Starting light follow at vehicle frame 17724, at distance 1846.60 m.
```

I dont see how this physically possible, but maybe this explains something:

```shell
142.802|E|libbeamng.TechCom|Error reading from socket: closed
142.802|E|libbeamng.TechCom|Error reading from socket: closed
142.803|E|libbeamng.TechCom|Error reading from socket: closed
142.803|E|libbeamng.TechCom|Error reading from socket: closed
142.803|E|libbeamng.TechCom|Error reading from socket: closed
142.804|E|libbeamng.TechCom|Error reading from socket: closed
142.804|E|libbeamng.TechCom|Error reading from socket: closed
142.804|E|libbeamng.TechCom|Error reading from socket: closed
142.804|E|libbeamng.TechCom|Error reading from socket: closed
142.805|E|libbeamng.TechCom|Error reading from socket: closed
142.805|E|libbeamng.TechCom|Error reading from socket: closed
142.805|E|libbeamng.TechCom|Error reading from socket: closed
142.805|E|libbeamng.TechCom|Error reading from socket: closed
142.806|E|libbeamng.TechCom|Error reading from socket: closed
142.806|E|libbeamng.TechCom|Error reading from socket: closed
142.806|E|libbeamng.TechCom|Error reading from socket: closed
142.806|E|libbeamng.TechCom|Error reading from socket: closed
142.806|E|libbeamng.TechCom|Error reading from socket: closed
142.807|E|libbeamng.TechCom|Error reading from socket: closed
142.807|E|libbeamng.TechCom|Error reading from socket: closed
142.807|E|libbeamng.TechCom|Error reading from socket: closed
142.807|E|libbeamng.TechCom|Error reading from socket: closed
142.807|E|libbeamng.TechCom|Error reading from socket: tcp{client}: 0000020D7C4631C0 - closed
142.808|E|libbeamng.TechCom|Error reading from socket: tcp{client}: 0000020C89AD1128 - closed
142.808|E|libbeamng.TechCom|Error reading from socket: tcp{client}: 0000020CD8D35648 - closed
142.808|E|libbeamng.TechCom|Error reading from socket: tcp{client}: 0000020D86D1A560 - closed
142.808|E|libbeamng.TechCom|Error reading from socket: tcp{client}: 0000020C1CF036B0 - closed
142.809|E|libbeamng.TechCom|Error reading from socket: tcp{client}: 0000020D35EDF548 - closed
142.809|E|libbeamng.TechCom|Error reading from socket: tcp{client}: 0000020E22276028 - closed
142.809|E|libbeamng.TechCom|Error reading from socket: tcp{client}: 0000020E33328990 - closed
142.809|E|libbeamng.TechCom|Error reading from socket: tcp{client}: 0000020DF845E170 - closed
142.810|E|libbeamng.TechCom|Error reading from socket: tcp{client}: 0000020E2C704160 - closed
142.810|E|libbeamng.TechCom|Error reading from socket: tcp{client}: 0000020AA7C55AF0 - closed
142.810|E|libbeamng.TechCom|Error reading from socket: tcp{client}: 0000020D16607178 - closed
142.810|E|libbeamng.TechCom|Error reading from socket: tcp{client}: 0000020AA6E17058 - closed
142.810|E|libbeamng.TechCom|Error reading from socket: tcp{client}: 0000020AA7CD1010 - closed
142.811|E|libbeamng.TechCom|Error reading from socket: tcp{client}: 0000020B910E5178 - closed
142.811|E|libbeamng.TechCom|Error reading from socket: tcp{client}: 0000020C7682C598 - closed
142.811|E|libbeamng.TechCom|Error reading from socket: tcp{client}: 0000020DD5640658 - closed
142.811|E|libbeamng.TechCom|Error reading from socket: tcp{client}: 0000020D9CC27E40 - closed
142.812|E|libbeamng.TechCom|Error reading from socket: tcp{client}: 0000020D3229CE88 - closed
142.812|E|libbeamng.TechCom|Error reading from socket: tcp{client}: 0000020E1936D780 - closed
142.812|E|libbeamng.TechCom|Error reading from socket: tcp{client}: 0000020DEA57F4D8 - closed
142.812|E|libbeamng.TechCom|Error reading from socket: tcp{client}: 0000020D33800040 - closed
```

I do not know why the ZarrWriter proceeded to errenously attempt to flush the same chunks numerous times, but it continued like normal after.


```shell
Last logs from beamng.log, approximately 3 minutes into the simulation:
127.53319|D|libbeamng.AI| Could not find a road network, or closest road is too far
142.81696|E|libbeamng.TechCom| Error reading from socket: closed
142.81775|E|libbeamng.TechCom| Error reading from socket: closed
```





#### Bug #2

```shell
35.663|E|GELua.tech_techCore.TechGE|execution error: "[string "SFXSystem.setGlobalParameter('g_FadeTimeMS', ..."]:1: bad argument #2 to 'setGlobalParameter' (number expected, got table)"
```

Not a correct lua command, need to asssess what is correct arguement here, removed from now


#### Bug #3
```shell
28.233|E|GELua.scenario_scenarios.scenarios|Prefab: scenario_1 already exist in level. Rejecting loading of duplicate.
```
Cleanup doesn't occur here

