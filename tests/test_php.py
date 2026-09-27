"""PHP extraction, on Laravel-shaped code: namespaces and `use` imports
resolved through composer.json PSR-4, inheritance and traits, the static
and `parent::` call forms, and route files pointing at controller methods."""

import json

from codegraph.parser import parse_repo

COMPOSER = json.dumps({"autoload": {"psr-4": {"App\\": "app/"}}})


def edges(result, kind):
    return {(e.src, e.dst) for e in result.edges if e.kind == kind}


def laravel_app(make_repo, extra=None):
    files = {
        "composer.json": COMPOSER,
        "app/Models/User.php": """<?php

namespace App\\Models;

use Illuminate\\Foundation\\Auth\\User as Authenticatable;

/** An application user. */
class User extends Authenticatable
{
    use HasRoles;

    public static function admins() { return static::query(); }
}
""",
        "app/Models/HasRoles.php": """<?php

namespace App\\Models;

trait HasRoles
{
    public function isAdmin() {}
}
""",
        "app/Http/Controllers/Controller.php": """<?php

namespace App\\Http\\Controllers;

abstract class Controller
{
    public function __construct() {}
    protected function authorizeAdmin() {}
}
""",
        "app/Http/Controllers/UserController.php": """<?php

namespace App\\Http\\Controllers;

use App\\Models\\{User, HasRoles as Roles};

class UserController extends Controller
{
    public function __construct()
    {
        parent::__construct();
    }

    public function index()
    {
        $this->authorizeAdmin();
        $user = new User();
        $user->isAdmin();
        return User::admins();
    }
}
""",
        "routes/web.php": """<?php

use App\\Http\\Controllers\\UserController;
use Illuminate\\Support\\Facades\\Route;

Route::get('/users', [UserController::class, 'index']);
""",
    }
    files.update(extra or {})
    return parse_repo(make_repo(files))


def test_use_imports_resolve_through_psr4_and_vendor_stays_external(make_repo):
    result = laravel_app(make_repo)
    imports = edges(result, "imports")
    assert ("app/Http/Controllers/UserController.php", "app/Models/User.php") in imports
    assert ("app/Http/Controllers/UserController.php", "app/Models/HasRoles.php") in imports  # grouped + aliased use
    assert ("routes/web.php", "app/Http/Controllers/UserController.php") in imports
    assert not any(dst.startswith("vendor") for _, dst in imports)


def test_inheritance_traits_and_same_namespace_names(make_repo):
    result = laravel_app(make_repo)
    inherits = edges(result, "inherits")
    # Controller is in the same namespace, so it needs no `use` statement.
    assert (
        "app/Http/Controllers/UserController.php::UserController",
        "app/Http/Controllers/Controller.php::Controller",
    ) in inherits
    assert ("app/Models/User.php::User", "app/Models/HasRoles.php::HasRoles") in inherits
    # Authenticatable is Laravel's vendor User class, never the app's own User.
    assert ("app/Models/User.php::User", "app/Models/User.php::User") not in inherits
    assert result.nodes["app/Models/User.php::User"].docstring == "An application user."


def test_call_forms(make_repo):
    result = laravel_app(make_repo)
    calls = edges(result, "calls")
    ctrl = "app/Http/Controllers/UserController.php::UserController"
    assert (f"{ctrl}.__construct", "app/Http/Controllers/Controller.php::Controller.__construct") in calls  # parent::
    index_calls = {dst for src, dst in calls if src == f"{ctrl}.index"}
    # $this-> through inheritance, `new`, and a static call; $user->isAdmin() has an unknown receiver.
    assert index_calls == {
        "app/Http/Controllers/Controller.php::Controller.authorizeAdmin",
        "app/Models/User.php::User",
        "app/Models/User.php::User.admins",
    }


def test_route_file_links_to_controller_method(make_repo):
    calls = edges(laravel_app(make_repo), "calls")
    assert ("routes/web.php", "app/Http/Controllers/UserController.php::UserController.index") in calls


def test_resource_and_invokable_routes_link_to_controller_actions(make_repo):
    result = laravel_app(
        make_repo,
        {
            "app/Http/Controllers/PhotoController.php": """<?php

namespace App\\Http\\Controllers;

class PhotoController extends Controller
{
    public function index() {}
    public function show() {}
}
""",
            "app/Http/Controllers/PingController.php": """<?php

namespace App\\Http\\Controllers;

class PingController extends Controller
{
    public function __invoke() {}
}
""",
            "routes/api.php": """<?php

use App\\Http\\Controllers\\{PhotoController, PingController};
use Illuminate\\Support\\Facades\\Route;

Route::apiResource('photos', PhotoController::class);
Route::get('/ping', PingController::class);
""",
        },
    )
    controllers = "app/Http/Controllers"
    route_calls = {dst for src, dst in edges(result, "calls") if src == "routes/api.php"}
    # Only the resource actions the controller actually defines get an edge.
    assert route_calls == {
        f"{controllers}/PhotoController.php::PhotoController.index",
        f"{controllers}/PhotoController.php::PhotoController.show",
        f"{controllers}/PingController.php::PingController.__invoke",
    }


def test_blade_templates_are_skipped(make_repo):
    result = laravel_app(make_repo, {"resources/views/welcome.blade.php": "<h1>{{ $title }}</h1>\n"})
    assert not any(n.file.endswith(".blade.php") for n in result.nodes.values())


def test_without_composer_classes_resolve_by_file_name(make_repo):
    repo = make_repo(
        {
            "lib/Base.php": "<?php\nclass Base { function run() {} }\n",
            "lib/Child.php": "<?php\nclass Child extends Base { function go() { $this->run(); } }\n",
        }
    )
    result = parse_repo(repo)
    assert ("lib/Child.php::Child", "lib/Base.php::Base") in edges(result, "inherits")
    assert ("lib/Child.php::Child.go", "lib/Base.php::Base.run") in edges(result, "calls")
