# README
## Intial Setup
The project utilizes conda for it's environment as there is specific conda_forge packages we utilize, notably z5. z5 is a C++ lightweight Zarr file handler, it also operates on Version 2 Zarr files whilst other packages are Version 3. As our feature extraction is a C++ binary we've decided to keep using z5 even for the python interface code for simplicity.

Clone the repository:
```shell
git clone https://github.com/zoshesky-uaa/audiogen-beamngpy.git
```

### Conda Setup
First have conda (miniconda, etc.) installed, then:
1. Begin by making an environment in conda based on the requirements YAML.
```shell
conda env create -f requirements.yml
```
2. Then, activate the environment by name.
```shell
conda activate audiogen-env
```

After conda is setup, you will need to begin making adjustments to ``const.py`` as it has a majority of tweaks needed in any configured use. If the find doesn't find your BeamNG.tech application, set a manual override to BEAMNG_LOCATION_OVERRIDE before continuing with any generation applications.

Settings such as the multichannel input device (if used for BeamNG.tech then we suggest VoiceMeteer as a audio router), training hyperparameters, model adjustments, and number and amount of sound classification events are all tunable. These settings are passed in generation mode to the generation binary as a JSON input (though many are redundant as physical model construction is no longer in C++ for easy debugging and setup).

## Generation Mode
To begin, simply run the ``generate.py`` file. This will run a simulated loop with internal validation and collect files in the ``/trials``directory in order. Be aware of the standards set are both not perfect and also quite strict at times. For example it might be very well possible that whilst in a occluded environment (i.e. a tunnel) classification labels are still writing even though the audio is below an obvious noise floor. By contrast, even the slightest of knicks or damage to the player vehicle might trigger a re-trial due to damage threshold check.

Our criteria is set manually (albeit magic numbers) in ``/run/validation.py``, the ratio of 0.2-0.8 activity might  seem quite large, but the main controlling threshold is the per batch check present in  ``validation.py``. This threshold is much more effective at controlling the average over a large dataset then a hardcoded activity threshold over a single file, albeit still imperfect. You're welcome to tune these values if you need better distribution of data.

## Training Mode
To begin, simply run the ``train.py`` file. This will, in order, go through all trial files presented in ``/trials`` folder and train the selected model (the default is SED). Utilize ``--deit-init`` when running for the first time to load in a DeIT model weights as a basis for each model. To select the model you wish to train use either ``model-type SED`` or ``model-type DOA``. The final model is a saved TorchScript module for loading with the C++ frontend of PyTorch.