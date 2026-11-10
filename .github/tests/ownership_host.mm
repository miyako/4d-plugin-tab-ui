// Engine-boundary model adapted from system-beep d357fdcfef0e825e5d3a44aaaa8eae98a7b43d09.
#include "4DPlugin-tab-ui.h"
#include "PrivateTypes.h"
#include "EntryPoints.h"
#include <codecvt>
#include <cstring>
#include <locale>

static std::map<PA_Unichar*, size_t> strings;
static std::map<PA_Picture, int> pictures;
static std::map<PA_Handle, size_t> handles;
struct Reference { PA_Variable property; int owners; bool collection; };
static std::map<void*, Reference*> refs;
static bool nullEmpty, failHandle, failResize, mainThread, missing;
static std::string kind;
static CUTF16String expected;
static NSMutableString* identifier;
static OwnershipWindow* window;
static int actions, modes, syncs, asyncs;

static void check(bool valid, const char* message)
{
    if (!valid) { std::cerr << message << "\n"; std::exit(1); }
}
static CUTF16String utf16(const char* text)
{
    std::wstring_convert<std::codecvt_utf8_utf16<char16_t>, char16_t> codec;
    auto u = codec.from_bytes(text);
    return CUTF16String(reinterpret_cast<const PA_Unichar*>(u.data()), u.size());
}
static PA_Unistring makeString(const PA_Unichar* text)
{
    size_t units = 0;
    while (text && text[units]) ++units;
    PA_Unistring value = {};
    if (units || !nullEmpty) {
        value.fString = new PA_Unichar[units + 1];
        if (units) std::memcpy(value.fString, text, units * sizeof(PA_Unichar));
        value.fString[units] = 0;
        value.fLength = static_cast<PA_long32>(units);
        strings[value.fString] = units;
    }
    return value;
}
static void disposeString(PA_Unistring value)
{
    if (!value.fString) { check(!value.fLength, "null nonempty string"); return; }
    check(strings.count(value.fString), "duplicate/unowned string disposal");
    check(strings.at(value.fString) == static_cast<size_t>(value.fLength), "allocation length");
    strings.erase(value.fString);
    delete[] value.fString;
}
static void textEquals(PA_Unistring value, const CUTF16String& wanted)
{
    check(value.fLength == static_cast<PA_long32>(wanted.size()), "exact UTF16 unit length");
    check(value.fString || wanted.empty(), "missing string");
    if (value.fString) {
        check(strings.count(value.fString), "read after release");
        check(value.fString[value.fLength] == 0, "terminator boundary");
        check(CUTF16String(value.fString, value.fLength) == wanted, "exact text");
    }
}
static PA_Picture makePicture()
{
    PA_Picture p = new unsigned char(42);
    pictures[p] = 1;
    return p;
}
static void clear(PA_Variable*);
static Reference* makeRef(bool collection)
{
    auto r = new Reference{PA_CreateVariable(eVK_Undefined), 1, collection};
    refs[r] = r;
    return r;
}
static void releaseRef(void* p)
{
    if (!p) return;
    check(refs.count(p), "release dead reference");
    auto r = refs.at(p);
    check(r->owners > 0, "invalid reference balance");
    if (--r->owners) return;
    clear(&r->property);
    refs.erase(p);
    delete r;
}
static PA_Variable clone(PA_Variable v)
{
    if (v.fType == eVK_Unistring) v.uValue.fString = makeString(v.uValue.fString.fString);
    else if (v.fType == eVK_Picture) {
        check(pictures.count(v.uValue.fPicture), "copy dead picture");
        ++pictures[v.uValue.fPicture];
    } else if (v.fType == eVK_Object || v.fType == eVK_Collection) {
        void* p = v.fType == eVK_Object ? v.uValue.fObject : v.uValue.fCollection;
        if (p) { check(refs.count(p), "copy dead reference"); ++refs.at(p)->owners; }
    }
    return v;
}
static void clear(PA_Variable* v)
{
    switch (v->fType) {
    case eVK_Unistring: disposeString(v->uValue.fString); break;
    case eVK_Picture:
        if (v->uValue.fPicture) {
            auto p = v->uValue.fPicture;
            check(pictures.count(p), "release dead picture");
            if (--pictures[p] == 0) { pictures.erase(p); delete static_cast<unsigned char*>(p); }
        }
        break;
    case eVK_Object: releaseRef(v->uValue.fObject); break;
    case eVK_Collection: releaseRef(v->uValue.fCollection); break;
    case eVK_ArrayUnicode: {
        auto h = v->uValue.fArray.fData;
        check(handles.count(h), "clear dead array");
        auto values = reinterpret_cast<PA_Unistring*>(*h);
        for (PA_long32 i = 0; i <= v->uValue.fArray.fNbElements; ++i) disposeString(values[i]);
        std::free(*h); delete h; handles.erase(h);
        break;
    }
    case eVK_Undefined: case static_cast<char>(eVK_Null):
    case eVK_Boolean: case eVK_Real: case eVK_Longint: break;
    default: check(false, "clear unspecified failed/raw-kind0 return");
    }
    v->fType = eVK_Undefined;
    v->fFiller = 0;
}
static PA_Variable resultValue()
{
    PA_Variable v = PA_CreateVariable(eVK_Undefined);
    if (kind == "string") {
        auto s = makeString(expected.c_str()); PA_SetStringVariable(&v, &s);
    } else if (kind == "picture") PA_SetPictureVariable(&v, makePicture());
    else if (kind == "object") PA_SetObjectVariable(&v, makeRef(false));
    else if (kind == "collection") PA_SetCollectionVariable(&v, makeRef(true));
    else if (kind == "boolean") PA_SetBooleanVariable(&v, true);
    else if (kind == "real") PA_SetRealVariable(&v, 3.25);
    else check(false, "unknown result kind");
    return v;
}
static void failedResult(PA_Variable* v)
{
    std::memset(v, kind == "error-poison" ? 0xa5 : 0, sizeof(*v));
}
static void host(short selector, EngineBlock* eb)
{
    switch (selector) {
    case EX_CREATE_UNISTRING:
        eb->fUniString1 = makeString(reinterpret_cast<PA_Unichar*>(eb->fHandle)); break;
    case EX_DISPOSE_UNISTRING: disposeString(eb->fUniString1); break;
    case EX_SET_UNISTRING: {
        auto replacement = makeString(reinterpret_cast<PA_Unichar*>(eb->fHandle));
        disposeString(eb->fUniString1); eb->fUniString1 = replacement; break;
    }
    case EX_VARIABLE_TO_STRING: {
        auto v = reinterpret_cast<PA_Variable*>(eb->fHandle);
        check(v->fType == eVK_Unistring, "reading failed/non-string variable");
        textEquals(v->uValue.fString, expected);
        eb->fUniString1 = v->uValue.fString; break;
    }
    case EX_GET_HWND: eb->fHandle = reinterpret_cast<PA_Handle>(window); break;
    case EX_CREATE_PICTURE: eb->fPicture = makePicture(); break;
    case EX_CLEAR_VARIABLE: clear(static_cast<PA_Variable*>(eb->fPtr1)); break;
    case EX_SET_OBJ_VALUE: {
        check(refs.count(eb->fPtr1), "set dead object");
        textEquals(eb->fUniString1, utf16("key"));
        auto r = refs.at(eb->fPtr1);
        clear(&r->property);
        r->property = clone(*static_cast<PA_Variable*>(eb->fPtr2));
        break;
    }
    case EX_GET_OBJ_VALUE: {
        check(refs.count(eb->fPtr1), "get dead object");
        textEquals(eb->fUniString1, utf16("key"));
        auto v = static_cast<PA_Variable*>(eb->fPtr2);
        if (kind.find("error-") == 0) {
            failedResult(v); eb->fError = eER_IncompatibleTypes;
        } else *v = resultValue();
        break;
    }
    case EX_HANDLE_MANAGER: {
        auto h = eb->fHandle;
        switch (eb->fParam1) {
        case 1:
            if (failHandle) { eb->fHandle = nullptr; eb->fError = eER_IncompatibleTypes; break; }
            h = new char*;
            *h = static_cast<char*>(std::calloc(1, std::max<sLONG_PTR>(1, eb->fParam2)));
            check(*h, "test handle allocation failed");
            handles[h] = eb->fParam2; eb->fHandle = h; break;
        case 2:
            check(handles.count(h), "dispose dead handle");
            std::free(*h); delete h; handles.erase(h); break;
        case 3: {
            check(handles.count(h), "resize dead handle");
            if (failResize) { eb->fError = eER_IncompatibleTypes; break; }
            auto data = static_cast<char*>(std::realloc(*h, std::max<sLONG_PTR>(1, eb->fParam2)));
            check(data, "test resize allocation failed");
            *h = data; handles[h] = eb->fParam2; break;
        }
        case 4: check(handles.count(h), "size dead handle"); eb->fParam2 = handles[h]; break;
        case 5: check(handles.count(h), "lock dead handle"); eb->fParam3 = reinterpret_cast<sLONG_PTR>(*h); break;
        case 6: check(handles.count(h), "unlock dead handle"); break;
        default: check(false, "unexpected handle operation");
        }
        break;
    }
    case EX_EXECUTE_COMMAND_BY_ID: {
        auto args = static_cast<PA_Variable**>(eb->fPtr1);
        auto v = static_cast<PA_Variable*>(eb->fPtr2);
        check(v->fType == eVK_Undefined, "command result initialization");
        if (eb->fParam1 == 1231) {
            check(refs.count(args[0]->uValue.fObject), "existence on dead object");
            textEquals(args[1]->uValue.fString, utf16("key"));
            PA_SetBooleanVariable(v, !missing);
        } else if (eb->fParam1 == 1225) {
            if (kind == "error-copy") {
                failedResult(v); eb->fError = eER_IncompatibleTypes;
            } else {
                auto copy = makeRef(false);
                copy->property = clone(refs.at(args[0]->uValue.fObject)->property);
                PA_SetObjectVariable(v, copy);
                if (kind == "error-handle") failHandle = true;
            }
        } else if (eb->fParam1 == 1217) {
            check(refs.count(args[0]->uValue.fObject), "stringify dead argument");
            if (kind.find("error-") == 0) {
                failedResult(v); eb->fError = eER_IncompatibleTypes;
            } else *v = resultValue();
        } else check(false, "unexpected command");
        break;
    }
    default: std::cerr << "unexpected engine selector " << selector << "\n"; std::exit(1);
    }
}

@implementation OwnershipWindow
- (NSString *)tabbingIdentifier { return identifier; }
- (void)setTabbingIdentifier:(NSString *)value { [identifier setString:value]; }
- (void)setTabbingMode:(NSWindowTabbingMode)mode
{
    check(mode == (expected.empty() ? NSWindowTabbingModeDisallowed :
                   modes ? NSWindowTabbingModeAutomatic : NSWindowTabbingModePreferred),
          "exact setter mode");
    ++modes;
}
- (void)toggleTabOverview:(id)sender { check(!sender, "unexpected sender"); ++actions; }
- (void)toggleTabBar:(id)sender { check(!sender, "unexpected sender"); ++actions; }
- (void)mergeAllWindows:(id)sender { check(!sender, "unexpected sender"); ++actions; }
- (void)selectNextTab:(id)sender { check(!sender, "unexpected sender"); ++actions; }
- (void)selectPreviousTab:(id)sender { check(!sender, "unexpected sender"); ++actions; }
@end
@implementation OwnershipThread
+ (BOOL)isMainThread { return mainThread; }
@end
dispatch_queue_t OwnershipQueue() { return reinterpret_cast<dispatch_queue_t>(1); }
void OwnershipSync(dispatch_queue_t queue, dispatch_block_t block)
{
    check(queue == OwnershipQueue(), "unexpected queue");
    ++syncs; block();
    // Invalidate a borrowed getter result after its protected read has finished.
    if (kind == "invalidate") [identifier setString:@"changed after main-thread block"];
}
void OwnershipAsync(dispatch_queue_t queue, dispatch_block_t block)
{ check(queue == OwnershipQueue(), "unexpected queue"); ++asyncs; block(); }
void OwnershipScale(CGContextRef, CGFloat, CGFloat) { check(false, "unexpected drawing"); }
void OwnershipTranslate(CGContextRef, CGFloat, CGFloat) { check(false, "unexpected drawing"); }

static void arrayCase()
{
    auto ar = PA_CreateVariable(eVK_ArrayUnicode);
    PA_ResizeArray(&ar, 3);
    for (int repeat = 0; repeat < 20; ++repeat) {
        for (int i = 0; i <= 3; ++i) {
            auto owned = makeString(expected.c_str());
            PA_SetStringInArray(ar, i, &owned);
            textEquals(PA_GetStringInArray(ar, i), expected);
        }
        auto borrowed = PA_GetStringInArray(ar, 1);
        auto copied = PA_CreateUnistring(borrowed.fString);
        PA_SetStringInArray(ar, 1, &copied);
        for (int i = 0; i < 10; ++i) {
            auto churn = makeString(expected.c_str()); PA_DisposeUnistring(&churn);
        }
        textEquals(PA_GetStringInArray(ar, 1), expected);
    }
    PA_ResizeArray(&ar, 1);
    auto owned = makeString(expected.c_str());
    auto wrong = PA_CreateVariable(eVK_Longint);
    PA_SetStringInArray(wrong, 0, &owned);
    PA_SetStringInArray(ar, -1, &owned);
    PA_SetStringInArray(ar, 2, &owned);
    auto noData = ar; noData.uValue.fArray.fData = nullptr;
    PA_SetStringInArray(noData, 0, &owned);
    PA_SetStringInArray(ar, 0, nullptr);
    textEquals(owned, expected); PA_DisposeUnistring(&owned);
    PA_ClearVariable(&ar);
}
static void dispatchCase(const std::string& name)
{
    mainThread = name == "dispatch-main";
    identifier = [[NSMutableString alloc] initWithCharacters:expected.data() length:expected.size()];
    window = name == "dispatch-nil" ? nil : [[OwnershipWindow alloc] init];
    PA_long32 number = 42, mode = 1;
    auto input = makeString(expected.c_str()), output = makeString(nullptr);
    PA_Unistring* result = &output;
    void* args[] = {&number, &input, &mode};
    PluginBlock p = {}; p.fParameters = args; p.fResult = reinterpret_cast<void*>(&result);
    PluginMain(2, &p);
    textEquals(output, window ? expected : CUTF16String());
    if (kind != "invalidate") {
        PluginMain(3, &p);
        check([identifier isEqualToString:[NSString stringWithCharacters:expected.data() length:expected.size()]], "setter content");
        mode = 0; PluginMain(3, &p);
        for (int i : {1, 4, 5, 6, 7}) PluginMain(i, &p);
        PluginMain(0, nullptr); PluginMain(999, nullptr);
        check(actions == (window ? 5 : 0) && modes == (window ? 2 : 0), "dispatcher selector counts");
        check(asyncs == 5 && syncs == (mainThread ? 0 : 3), "synthetic queue counts");
    }
    PA_DisposeUnistring(&input); PA_DisposeUnistring(&output);
    [window release]; window = nil; [identifier release]; identifier = nil;
}
static void helperCase(const std::string& name, const char* raw)
{
    auto object = makeRef(false);
    if (name == "set-narrow") ob_set_s(object, "key", raw);
    else if (name == "set-wide") ob_set_s(object, L"key", raw);
    else if (name == "set-wchars") {
        std::wstring_convert<std::codecvt_utf8<wchar_t>> codec;
        auto wide = codec.from_bytes(raw); ob_set_a(object, L"key", wide.c_str());
    } else if (name == "set-utf16") ob_set_a(object, L"key", &expected);
    else if (name == "set-picture") {
        ob_set_p(object, L"key", makePicture());
        check(pictures.at(object->property.uValue.fPicture) == 1, "property retains transferred picture");
    }
    else if (name == "get-a") {
        CUTF8String value(reinterpret_cast<const uint8_t*>("unchanged"));
        check(ob_get_a(object, L"key", &value) == !missing, "existence boolean preserved");
        const char* wanted = kind == "string" && !missing ? raw : "unchanged";
        check(value == CUTF8String(reinterpret_cast<const uint8_t*>(wanted)), "getter output");
    } else if (name == "get-b") check(ob_get_b(object, L"key") == (kind == "boolean" && !missing), "boolean getter");
    else if (name == "get-n") check(ob_get_n(object, L"key") == (kind == "real" && !missing ? 3.25 : 0.0), "real getter");
    else if (name == "get-c") {
        auto c = ob_get_c(object, L"key");
        check((c != nullptr) == (kind == "collection" && !missing), "collection handoff");
        if (c) { check(refs.count(c), "premature collection release"); PA_DisposeCollection(c); }
    } else if (name == "get-o") {
        auto o = ob_get_o(object, L"key");
        check((o != nullptr) == (kind == "object" && !missing), "object handoff");
        if (o) { check(refs.count(o), "premature object release"); PA_DisposeObject(o); }
    } else if (name == "stringify") {
        CUTF8String value(reinterpret_cast<const uint8_t*>("unchanged"));
        ob_stringify(object, &value);
        const char* wanted = kind == "string" ? raw : "unchanged";
        check(value == CUTF8String(reinterpret_cast<const uint8_t*>(wanted)), "stringify output");
    } else if (name == "values") {
        ob_set_i(object, L"key", 42); check(object->property.uValue.fLongint == 42, "integer setter");
        ob_set_n(object, L"key", 3.25); check(object->property.uValue.fReal == 3.25, "wide real setter");
        ob_set_n(object, "key", 3.25); check(object->property.uValue.fReal == 3.25, "narrow real setter");
        ob_set_b(object, L"key", true); check(object->property.uValue.fBoolean, "boolean setter");
        ob_set_0(object, L"key"); check(object->property.fType == static_cast<char>(eVK_Null), "wide null setter");
        ob_set_0(object, "key"); check(object->property.fType == static_cast<char>(eVK_Null), "narrow null setter");
        auto child = makeRef(false);
        ob_set_o(object, L"key", child); check(refs.at(child)->owners == 1, "wide object transfer");
        auto other = makeRef(false);
        ob_set_o(object, "key", other); check(refs.at(other)->owners == 1, "narrow object transfer");
        auto collection = makeRef(true);
        ob_set_c(object, L"key", collection); check(refs.at(collection)->owners == 1, "collection transfer");
        check(ob_is_defined(object, L"key"), "defined property");
    } else check(false, "unknown helper");
    if (name.find("set-") == 0 && name != "set-picture") textEquals(object->property.uValue.fString, expected);
    PA_DisposeObject(object);
}
int main(int argc, char** argv)
{
    @autoreleasepool {
        check(argc == 5, "arguments");
        gCall4D = host;
        const std::string name = argv[1];
        expected = utf16(argv[2]); nullEmpty = std::string(argv[3]) == "null"; kind = argv[4];
        if (name == "array") arrayCase();
        else if (name.find("dispatch-") == 0) dispatchCase(name);
        else if (name == "missing") {
            missing = true;
            for (const char* getter : {"get-a", "get-b", "get-n", "get-c", "get-o"}) helperCase(getter, argv[2]);
        } else if (name == "null-controls") {
            CUTF8String value(reinterpret_cast<const uint8_t*>("unchanged"));
            check(!ob_get_a(nullptr, L"key", &value), "null string getter");
            check(!ob_get_b(nullptr, L"key") && ob_get_n(nullptr, L"key") == 0.0 &&
                  !ob_get_c(nullptr, L"key") && !ob_get_o(nullptr, L"key") &&
                  !ob_is_defined(nullptr, L"key"), "null getters");
            ob_set_s(nullptr, "key", "text"); ob_set_s(nullptr, L"key", "text");
            ob_set_a(nullptr, L"key", L"text"); ob_set_a(nullptr, L"key", &expected);
            ob_set_p(nullptr, L"key", nullptr); ob_set_o(nullptr, L"key", nullptr);
            ob_set_o(nullptr, "key", nullptr); ob_set_c(nullptr, L"key", nullptr);
            ob_set_s(nullptr, L"key", nullptr); ob_set_a(nullptr, L"key", static_cast<const wchar_t*>(nullptr));
            ob_stringify(nullptr, &value);
            check(value == CUTF8String(reinterpret_cast<const uint8_t*>("unchanged")), "null output");
        } else if (name == "sdk-failures") {
            failHandle = true; auto h = PA_NewHandle(8);
            check(!h && PA_GetLastError() != eER_NoErr, "handle failure predicate");
            failHandle = false; h = PA_NewHandle(8); failResize = true;
            check(!PA_SetHandleSize(h, 16) && PA_GetLastError() != eER_NoErr, "resize failure predicate");
            check(handles.at(h) == 8, "model preserved capacity");
            failResize = false; PA_DisposeHandle(h);
        } else helperCase(name, argv[2]);
        check(strings.empty(), "unreleased string owner");
        check(pictures.empty(), "unreleased picture owner");
        check(handles.empty(), "unreleased handle owner");
        check(refs.empty(), "unreleased object/collection owner");
        std::cout << "strings=0 pictures=0 handles=0 objects=0 collections=0\n";
    }
}
