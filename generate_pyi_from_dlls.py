from pythonnet import load
load("coreclr")  # or "netfx" for .NET Framework — must be called before import clr

import clr

cs_to_python = {
    "Int32": "int",
    "Int64": "long",
    "Float32": "float",
    "Float64": "double",
    "String": "str",
    "Boolean": "bool",
    "Void": "None",
    "Type": "type",
    "Object": "object",
    "Byte[]": "bytes",
    "String[]": "list[str]",
    "Boolean[]": "list[bool]",
}
def pythonize(type_name):
    return cs_to_python.get(type_name, type_name)

def get_params(m):
    params = ["self"]
    params.extend(p.Name + ": " + pythonize(p.ParameterType.Name) for p in m.GetParameters())
    return params

def from_reference(ref_name: str):
    with open(ref_name + ".pyi", "w") as f:
        ref = clr.AddReference(ref_name)
        for t in ref.GetTypes():
            print(f"class {t.Name}:", file=f) # decide what to do with t.IsPublic
            for c in t.GetConstructors():
                print(
                    f"  def __init__({', '.join(get_params(c))}): ...",
                    file=f)
            for m in t.GetMethods():
                params = get_params(m)
                print(
                    f"  def {m.Name}({', '.join(get_params(m))}) -> {pythonize(m.ReturnType.Name)}: ...",
                    file=f)

from_reference("Civ3Tools")