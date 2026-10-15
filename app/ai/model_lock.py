"""One lock shared by every big AI model (the search embedding model and the review
sentiment model), held while a model is LOADING.

Loading is when memory use peaks: the weights are read from disk and copied into
torch tensors. On the 4 GB dev laptop, two models loading at once (e.g. the search model
being preloaded right after login while a customer saves their first review) could push
the machine into swapping. With this lock the second load simply waits for the first.
"""

import threading

LOADING = threading.Lock()
