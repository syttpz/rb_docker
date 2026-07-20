# corelink cpp 库编译补丁说明

## 背景

在把 `corelink_cpp/` 下的 Corelink C++ 客户端作为 `ros2_bridge_node`(桥接
ROS2 topic 和 Corelink stream 的新模块,见
`/home/syttpz/.claude/plans/ros2-dds-plan-rmw-ethereal-fog.md`)的依赖来编译时,
在这台开发机上遇到了编译/链接失败:

- 系统:Ubuntu 22.04 (Jammy)
- 编译器:GCC 11.4.0
- `libasio-dev` 1:1.18.1-1(apt)
- `rapidjson-dev` 1.1.0+dfsg2-7(apt)
- `libwebsockets-dev` 4.0.20-2ubuntu1.1(apt)
- `libssl-dev` 3.0.2(apt)

一共发现 3 个问题,**全都是 `corelink_cpp/` 里本来就存在的 bug,跟 `ros2_bridge_node`
自己写的代码无关**——换句话说,任何人在类似新一点的工具链上从头编译这个库,
大概率都会踩到。之所以直接改在 `corelink_cpp/` 里,而不是绕开修,是因为这些都是通用的
正确性/可移植性问题,不是只针对 `ros2_bridge_node` 的特殊行为。

## 补丁 1:缺少 `#include <cstring>`

**文件:** `corelink_cpp/include/core/corelink_network_constants.hpp`

`protocol::operator==`(第 79 行)用到了 `std::strcmp`,但这个头文件从来
没有 `#include <cstring>`。之前之所以能编译过,大概率是因为别的头文件
碰巧间接引入了 `<cstring>`——这种"间接引入"不是语言保证的,在这台机器的
libstdc++ 版本上就不成立了。报错:

```
error: 'strcmp' is not a member of 'std'
```

**修法:** 在文件开头直接加 `#include <cstring>`。没有任何行为变化,
只是让一个本来就在用的符号,不再依赖"运气好被间接引入"。

## 补丁 2:`connect_timeout_secs` 在 libwebsockets 4.0.20 里不存在

**文件:** `corelink_cpp/src/core/corelink_data_xchg_websocket_proto_manager.cc`
(`make_context()` 函数)

代码里无条件地写了
`m_context_create_info.connect_timeout_secs = 60;`。
`lws_context_creation_info` 结构体的这个字段,是比 `libwebsockets 4.0.20`
(也就是 Ubuntu 22.04 apt 装的这个版本)更新的版本才加进去的。报错:

```
error: 'struct lws_context_creation_info' has no member named 'connect_timeout_secs'
```

**修法:** 用 `#if defined(LWS_LIBRARY_VERSION_NUMBER) && LWS_LIBRARY_VERSION_NUMBER >= 4001000`
把这行赋值包起来。在版本够新的 libwebsockets 上,这行代码照常执行,行为完全不变
(连接建立阶段的超时上限仍是 60 秒);在版本旧的 libwebsockets(比如这台机器)上,
这行会被跳过,lws 会退回用它自己的默认连接超时——上面单独设置的 `timeout_secs`
(整体 socket 超时)在两种情况下都照样生效。这只是在老版本 libwebsockets 上收窄了
一个调参旋钮的可控范围,不影响 Corelink 协议本身的任何行为。

*(备注:没有精确查到 `connect_timeout_secs` 具体是从哪个 libwebsockets 版本开始
加入的,`4001000` 是"肯定比 4.0.20 新"的保守估计。如果发现这个版本判断在某个环境下
不对,应该调整这个版本号阈值,而不是直接去掉这个判断。)*

## 补丁 3:头文件里的静态成员定义没加 `inline`,导致重复定义(违反 ODR)

**文件:** `corelink_cpp/include/core/corelink_client_connection_info.hpp`
(文件末尾,`struct` 定义之外)

```cpp
const_ptr_to_const_val<char> corelink_client_connection_info::CORELINK_REMOTE_HOSTNAME = "corelink.hsrn.nyu.edu";
const_ptr_to_const_val<char> corelink_client_connection_info::DEFAULT_USERNAME = "Testuser";
const_ptr_to_const_val<char> corelink_client_connection_info::DEFAULT_PASSWORD = "Testpassword";
```

这是把类外的静态成员**定义**直接写在头文件里,但没加 `inline`。每一个
`.cpp` 文件只要(哪怕间接地通过 `corelink_all.hpp`)include 了这个头文件,
就会各自生成一份这三个符号的定义——单独看语法上没问题,但只要同一个链接单元里
有超过一个 `.cpp` 文件 include 了它,就违反了 C++ 的"单一定义原则"(ODR)。
`ros2_bridge_node` 正好踩中了这个情况(`main.cpp`、`bridge_node.cpp`、
`corelink_transport.cpp` 三个文件都 include 了它)。之前所有用过这个客户端的
例子(比如 `basic-connect-test.cpp`)都只有单独一个 `.cpp` 文件,所以这个问题
一直没暴露出来。链接报错:

```
multiple definition of `corelink::client::corelink_client_connection_info::CORELINK_REMOTE_HOSTNAME'
```

**修法:** 给这三处定义都加上 `inline`。这是 C++17 里"在头文件里安全定义静态数据
成员"的标准做法(inline 变量在多个翻译单元之间会被合并成同一份,而不是各自独立
的定义)。没有任何行为变化。

*后续可以关注一下:"类外静态成员定义写在头文件里、没加 inline"这个模式,
`corelink_cpp/include/` 下别的地方可能也存在——简单搜了一下没找到别的实例,但没有做
穷尽式排查。如果以后这个库又多接了几个 `.cpp` 文件、又冒出"重复定义"的链接
报错,先往这个方向查。*

## 没有采用的方案

也考虑过换一个更新版本的 libwebsockets(自己编译安装),而不是打补丁绕过。
对于一个研究原型来说,这个方案依赖体积增加得更多,而且可能引入新的兼容性问题
(比如 TLS 后端版本跟系统 OpenSSL 对不上),所以暂时没采用。如果以后
`ros2_bridge_node` 真的需要某些被新版本 libwebsockets 才有的特性,再回头考虑。
