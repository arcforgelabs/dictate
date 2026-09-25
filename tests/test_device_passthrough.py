import unittest

from dictate.stt.factory import device_for_host, passthrough_blocks_cuda

VFIO_4090 = """
01:00.0 VGA compatible controller: NVIDIA Corporation AD102 [GeForce RTX 4090]
\tKernel driver in use: vfio-pci
"""

HOST_4090 = """
01:00.0 VGA compatible controller: NVIDIA Corporation AD102 [GeForce RTX 4090]
\tKernel driver in use: nvidia
"""

VFIO_4090_AND_HOST_CARD = """
01:00.0 VGA compatible controller: NVIDIA Corporation AD102 [GeForce RTX 4090]
\tKernel driver in use: vfio-pci

02:00.0 VGA compatible controller: NVIDIA Corporation GA102 [GeForce RTX 3080]
\tKernel driver in use: nvidia
"""


class DevicePassthroughTests(unittest.TestCase):
    def test_vfio_4090_forces_cpu(self) -> None:
        self.assertTrue(passthrough_blocks_cuda(VFIO_4090))
        self.assertEqual(device_for_host("auto", VFIO_4090), "cpu")
        self.assertEqual(device_for_host("cuda", VFIO_4090), "cpu")

    def test_host_4090_stays_available(self) -> None:
        self.assertFalse(passthrough_blocks_cuda(HOST_4090))
        self.assertEqual(device_for_host("auto", HOST_4090), "auto")

    def test_a_free_gpu_is_kept_when_the_4090_is_passed_through(self) -> None:
        self.assertFalse(passthrough_blocks_cuda(VFIO_4090_AND_HOST_CARD))
        self.assertEqual(device_for_host("cuda", VFIO_4090_AND_HOST_CARD), "cuda")

    def test_cpu_request_is_unchanged(self) -> None:
        self.assertEqual(device_for_host("cpu", VFIO_4090), "cpu")


if __name__ == "__main__":
    unittest.main()
