import os
import pathlib
import struct
import unittest


def _repository_file(apparent, relative):
    runfiles = pathlib.Path(os.environ["RUNFILES_DIR"])
    mapping = runfiles / "_repo_mapping"
    for line in mapping.read_text(encoding="utf-8").splitlines():
        fields = line.split(",", 2)
        if len(fields) == 3 and fields[1] == apparent:
            direct = runfiles / fields[2] / relative
            if direct.is_file():
                return direct
            return runfiles / "_main/external" / fields[2] / relative
    raise AssertionError("%s is absent from runfiles mapping" % apparent)


def _python_executable():
    return _repository_file("mkosi_debian_python", "python")


class DebianPythonHermeticTest(unittest.TestCase):
    def _assert_static(self, executable):
        data = executable.read_bytes()
        self.assertEqual(data[:4], b"\x7fELF")
        self.assertEqual(data[4], 2)
        self.assertEqual(data[5], 1)
        header = struct.unpack_from("<16sHHIQQQIHHHHHH", data)
        program_header_offset = header[5]
        program_header_size = header[9]
        program_header_count = header[10]
        dynamic = False
        for index in range(program_header_count):
            offset = program_header_offset + index * program_header_size
            program_header = struct.unpack_from("<IIQQQQQQ", data, offset)
            segment_type = program_header[0]
            if segment_type == 3:
                self.fail("static managed Python unexpectedly has PT_INTERP")
            if segment_type == 2:
                dynamic = True
        self.assertFalse(dynamic, "static managed Python unexpectedly has PT_DYNAMIC")

    def test_static_bootstrap_has_no_interpreter_or_needed_libraries(self):
        self._assert_static(_python_executable())
        for host_library in (b"libc.so", b"libm.so", b"libpthread.so", b"ld-linux"):
            self.assertNotIn(host_library, _python_executable().read_bytes())

    def test_static_namespace_bootstrap_has_no_interpreter_or_needed_libraries(self):
        self._assert_static(_repository_file("mkosi_debian_tools", "namespace_runner"))
        self._assert_static(_repository_file("mkosi_debian_tools", "launcher"))


if __name__ == "__main__":
    unittest.main()
