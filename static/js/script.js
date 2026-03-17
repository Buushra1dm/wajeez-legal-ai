function toggleMenu() {
    const navLinks = document.getElementById("nav-Links");
    if (navLinks) {
        navLinks.classList.toggle("active");
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const flashes = document.querySelectorAll(".flash-message");
    flashes.forEach((message, index) => {
        window.setTimeout(() => {
            message.classList.add("is-visible");
        }, 80 * index);
    });

    const textInput = document.getElementById("text-input");
    const textCounter = document.getElementById("text-counter");
    if (textInput && textCounter) {
        const updateCounter = () => {
            textCounter.textContent = `${textInput.value.length} حرف`;
        };
        updateCounter();
        textInput.addEventListener("input", updateCounter);
    }

    document.querySelectorAll("form").forEach((form) => {
        form.addEventListener("submit", () => {
            const submitButton = form.querySelector("button[type='submit']");
            if (!submitButton) {
                return;
            }
            if (submitButton.dataset.loadingText) {
                submitButton.textContent = submitButton.dataset.loadingText;
            }
            submitButton.disabled = true;
            submitButton.classList.add("is-loading");
        });
    });
});
