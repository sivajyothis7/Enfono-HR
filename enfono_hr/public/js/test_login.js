console.log("✅ Custom login JS loaded");

document.addEventListener("DOMContentLoaded", function () {
    const title = document.querySelector("h1");
    if (title) title.innerText = "🚀 Custom Login Page";

    // Optional: alert or log input
    const loginBtn = document.querySelector(".btn-login");
    if (loginBtn) {
        loginBtn.addEventListener("click", () => {
            const username = document.querySelector("#login_email").value;
            console.log("Attempting login for:", username);
        });
    }
});
