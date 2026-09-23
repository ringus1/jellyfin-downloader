from tqdm import tqdm


class DummyBuffer:
    """Lightweight dummy buffer providing len() without allocating memory."""

    def __init__(self, size: int):
        self._size = size

    def __len__(self) -> int:
        return self._size


class TestDownloadProgressBar:
    """Verifies that progress bar rendering handles estimated size discrepancies gracefully."""

    def test_handles_download_exceeding_estimated_size_without_formatting_error(self):
        expected_size = 509.11
        bar_fmt = "{percentage:3.0f}%|{bar}| {n:.2f}/{total_fmt} MB [{elapsed}<{remaining}, {rate_fmt}{postfix}]"

        with tqdm(
            total=expected_size,
            unit="MB",
            initial=0,
            bar_format=bar_fmt,
        ) as pbar:

            def pbar_update(buffer):
                delta = len(buffer) / (1024 * 1024)
                if pbar.total is not None and (pbar.n + delta > pbar.total):
                    pbar.total = round(pbar.n + delta, 2)
                pbar.update(delta)

            # Simulate downloading 507.94 MB first
            buffer_chunk_1 = DummyBuffer(int(507.94 * 1024 * 1024))
            pbar_update(buffer_chunk_1)

            # Simulate final chunk exceeding original estimate (total 510.44 MB)
            buffer_chunk_2 = DummyBuffer(int(2.5 * 1024 * 1024))
            pbar_update(buffer_chunk_2)

            # Verify no exception was raised, total expanded, and pbar closed safely
            assert pbar.total >= pbar.n
            assert round(pbar.n, 2) == 510.44

    def test_handles_zero_expected_size_gracefully(self):
        expected_size = 0
        bar_fmt = "{n:.2f} MB [{elapsed}, {rate_fmt}{postfix}]"

        with tqdm(
            total=expected_size,
            unit="MB",
            initial=0,
            bar_format=bar_fmt,
        ) as pbar:
            pbar.update(10.5)
            assert pbar.n == 10.5
