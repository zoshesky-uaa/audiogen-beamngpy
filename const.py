import os
# Optional BeamNG home override. Leave unset for automatic discovery.

BEAMNG_LOCATION_OVERRIDE = r"E:\BeamNG.tech.v0.38.3.0" 
BEAMNG_LOCATION = BEAMNG_LOCATION_OVERRIDE or os.environ.get("BEAMNG_LOCATION")

# Defines whether the simulation is in training mode (AI-controlled) or not (human-controlled)
TRAINING = True

# Audio configuration, FFT parameters
AUDIO_INPUT_DEVICE_NAME = "Voicemeeter Out B1 (VB-Audio Voicemeeter VAIO)"

# Simulation configuration
MAXIMUM_TRAFFIC_VEHICLES = 8
MAXIMUM_SPAWN_WAIT_TIME_SECONDS = 120

GEN_BINARY_PATH = "bin/accdoa_gen.exe" 

sample_rate = 16000 # Sample rate for audio capture (e.g., 16000 Hz)
fft_size = 512 # FFT size for the STFT
mel_bins = 128 # Number of Mel bands for the log-mel spectrogram
hop_length = 160 # Hop length
target_res = 0.1 # Target output resolution in second (i.e. 0.1s for 100ms)
batch_size = 24 # Batch size for training
se_count = 3 # Maximum unique sound events for SED head
track_count = 3 # Maximum amount of overlapping events for DOAE head

MAXIMUM_VEHICLES = track_count * se_count # Maximum total vehicles in the simulation, considering all classes

# Calculated/Constant parameters:
epochs = 50 # Number of training epochs
warmup_epochs = 5 # Number of warmup epochs for learning rate scheduling
batch_amount = 5 # Number of batches to process for training;
channels = 4 # Number of audio channels (e.g., 4 for first-order ambisonics)
time_window = 3
patch_size = 16 # Patch size (P) (h x w kernel)
patch_overlap = 6 # Patch overlap (O) 
enc_layers = 12 # Encoder layers (L) 
# --------------------------------
# These are specific dimension for distilling from other transformer models:
att_headers = 12; # Attention heads (h) : 12 
embed_dim = 768 # (h x 64) 
# --------------------------------
input_frame_time = hop_length / sample_rate # Time per frame (Tpf)
frame_time_seq = int(time_window * (sample_rate / hop_length)) # Frames per time window 
frame_max = int(frame_time_seq * batch_size * batch_amount) # Simulation maximum length in frames, approximately 6 minutes
conv_stride = patch_size - patch_overlap #Convolution stride (S) : (P - O)
fft_bins = int(fft_size // 2 + 1) # Number of frequency bins from the FFT
history_size = int(fft_size - hop_length) # Number of samples that overlap between consecutive STFT frames

# Temporal (time-features) Patches (n_t) : 29 (floor((T - P) / S) + 1)
# Frequency (mel-features) Patches (n_f) : 12 (floor((M - P) / S) + 1))
# Total Patches (n) = (n_t * n_f)

n_t = int((time_window * (sample_rate / hop_length) - patch_size) / conv_stride + 1)
n_f = int((mel_bins - patch_size) / conv_stride + 1)
num_patches = int(n_t * n_f) # Total Patches (n) (n_t * n_f)
t_prime = int(time_window / target_res)
label_max = t_prime * batch_size * batch_amount
total_seq = t_prime + num_patches # Total sequence length (seq) (t' + n)
inference_amount = int(target_res * (sample_rate / hop_length)) # Number of frames to infer on per inference step (e.g., 10 for 100ms)

# SED Features (sed_featureset)
# Concept: 1-channel log-mel spectrogram.
#     read_buffer: [1, config.frame_time_seq, config.mel_bins] (e.g., [1, 300, 128])
# x_in: [config.batch_size, 1, config.frame_time_seq, config.mel_bins] (e.g., [24, 1, 300, 128])

# DOA Features (doa_featureset)
# Concept: 5-channel features (1 log-mel + 4 intensity vectors).
# read_buffer: [5, config.frame_time_seq, config.mel_bins] (e.g., [5, 300, 128])
# x_in: [config.batch_size, 5, config.frame_time_seq, config.mel_bins] (e.g., [24, 5, 300, 128])

# SED Labels (sed_labelset)
# Concept: Binary flag reference per class track label.
# read_buffer: [1, config.frame_time_seq, (se_count * track_count * 1)]
# x_in: [config.batch_size, 1, config.frame_time_seq, (se_count * track_count * 1)]

# DOA Labels (doa_labelset)
# Concept: Flattened Cartesian coordinates (X, Y).
# read_buffer: [1, config.frame_time_seq, (se_count * track_count * 2)]
# x_in: [config.batch_size, 1, config.frame_time_seq, (se_count * track_count * 2)]

sed_fet_buffer_dim = (1, frame_time_seq, mel_bins) # SED feature buffer dimension
doa_fet_buffer_dim = (5, frame_time_seq, mel_bins) # DOA feature buffer dimension
sed_label_buffer_dim = (1, t_prime, int(se_count * track_count * 1)) # SED label buffer dimension
doa_label_buffer_dim = (1, t_prime, int(se_count * track_count * 2)) # DOA label buffer dimension
