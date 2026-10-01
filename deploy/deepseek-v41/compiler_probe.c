/* Build-time preflight for headers required by Triton's runtime C helpers.
 * Passing this probe is not proof of GPU kernels, model startup, or quality. */
#include <stdlib.h>
#include <Python.h>
#include <cuda.h>

int main(void) {
    return EXIT_SUCCESS;
}
